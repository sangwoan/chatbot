package com.geuhaeyeoreum.camera;

import java.io.ByteArrayOutputStream;
import java.io.File;
import java.io.FileInputStream;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.PublicKey;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.List;
import java.util.Map;
import java.util.Set;

/**
 * Over-the-air updates for the web part of the app (the page, its filters and UI), so most changes reach an
 * installed app without a new APK. The Android shell itself is never replaced: an update that needs a newer
 * shell is only reported, with the APK published next to it.
 *
 * - A bundle is accepted only if manifest.json is signed by the APK's own signing key (see UpdateBundle),
 *   names this package, is newer than what is installed and every file matches its SHA-256 and size.
 * - Each channel is resolved to an exact commit first (GitHub API), so all files come from one commit and
 *   no CDN cache can serve a stale or mixed set; the branch URL is the fallback.
 * - Files are staged in private storage (ota/tmp → ota/staged) and become ota/active at the next prepare().
 *   Files a bundle shares with the APK or the active bundle (same SHA-256) are copied, not downloaded.
 * - A bundle that fails to start is marked bad and dropped (markBadActive) and never fetched again.
 *
 * Pure Java (java.net/java.io/java.security plus org.json), so it can be exercised off-device.
 */
final class Updater {
    interface Listener {
        /** state: "ready" (staged), "native" (needs a newer APK), "none" (up to date) or "error". Called on a worker thread. */
        void onResult(String state, UpdateBundle bundle, String apkUrl, String error);
    }

    /** Files bundled in the APK, to avoid downloading ones that did not change. */
    interface Local {
        byte[] read(String rel, long limit) throws IOException;
    }

    /** Where updates are published: template contains {ref}; api (may be null) returns the branch head's commit SHA. */
    static final class Channel {
        final String template, ref, api;

        Channel(String template, String ref, String api) {
            this.template = template;
            this.ref = ref;
            this.api = api;
        }
    }

    private static final int MANIFEST_MAX = 64 * 1024;
    private static final long TOTAL_MAX = 24L << 20;

    private final File active, staged, tmp, badFile;
    private final Channel[] channels;
    private final PublicKey key;
    private final String pkg;
    private final int nativeCode, bundledBuild;
    private final Local local;
    private final Set<Integer> bad = new HashSet<>();
    private final List<Listener> waiting = new ArrayList<>();
    private volatile UpdateBundle activeBundle;
    /** The verified contents of ota/staged (null if none or not yet loaded); avoids re-hashing on every resume. */
    private UpdateBundle stagedBundle;
    private boolean stagedKnown;
    private boolean checking;

    Updater(File root, Channel[] channels, PublicKey key, String pkg, int nativeCode, int bundledBuild, Local local) {
        this.active = new File(root, "active");
        this.staged = new File(root, "staged");
        this.tmp = new File(root, "tmp");
        this.badFile = new File(root, "bad.txt");
        this.channels = channels;
        this.key = key;
        this.pkg = pkg;
        this.nativeCode = nativeCode;
        this.bundledBuild = bundledBuild;
        this.local = local;
        root.mkdirs();
        loadBad();
    }

    /** Promotes a newer staged bundle and drops stale or bad ones. Returns true when a staged bundle became active. */
    synchronized boolean prepare() {
        loadBad();
        UpdateBundle a = load(active), s = load(staged);
        stagedBundle = null;
        stagedKnown = false;
        boolean promoted = false;
        int base = Math.max(bundledBuild, a == null ? 0 : a.build);
        if (s != null && usable(s) && s.build > base) {
            deleteTree(active);
            if (staged.renameTo(active)) {
                a = s;
                promoted = true;
            } else {
                a = load(active);
            }
        } else if (staged.exists()) {
            deleteTree(staged);
        }
        if (a != null && (!usable(a) || a.build <= bundledBuild)) {
            deleteTree(active);
            a = null;
        }
        activeBundle = a;
        return promoted;
    }

    UpdateBundle active() {
        return activeBundle;
    }

    int currentBuild() {
        UpdateBundle a = activeBundle;
        return Math.max(bundledBuild, a == null ? 0 : a.build);
    }

    /** The file to serve for a page path, or null to fall back to the APK's assets. */
    File fileFor(String rel) {
        UpdateBundle a = activeBundle;
        return a != null && a.files.containsKey(rel) ? new File(active, rel) : null;
    }

    /** A verified staged update newer than what runs, or null. */
    synchronized UpdateBundle stagedUpdate() {
        if (!stagedKnown) {
            stagedBundle = load(staged);
            stagedKnown = true;
        }
        UpdateBundle s = stagedBundle;
        return s != null && usable(s) && s.build > currentBuild() ? s : null;
    }

    boolean stagedNewer() {
        return stagedUpdate() != null;
    }

    /** The active bundle failed to start: never use this build again and fall back to the APK's own page. */
    synchronized void markBadActive() {
        UpdateBundle a = activeBundle;
        if (a == null) return;
        bad.add(a.build);
        saveBad();
        deleteTree(active);
        activeBundle = null;
    }

    /**
     * Looks for a newer bundle on a worker thread and stages it. While a check runs, further callers wait for
     * its result instead of starting another one.
     */
    void check(final Listener l) {
        synchronized (this) {
            if (checking) {
                waiting.add(l);
                return;
            }
            checking = true;
        }
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                Object[] r;
                try {
                    r = runCheck();
                } catch (Throwable e) {
                    r = new Object[]{"error", null, null, String.valueOf(e)};
                }
                List<Listener> all = new ArrayList<>();
                all.add(l);
                synchronized (Updater.this) {
                    all.addAll(waiting);
                    waiting.clear();
                    checking = false;
                }
                for (Listener x : all) x.onResult((String) r[0], (UpdateBundle) r[1], (String) r[2], (String) r[3]);
            }
        }, "geuhae-update");
        t.setDaemon(true);
        t.start();
    }

    /** {state, bundle, apkUrl, error} */
    private Object[] runCheck() throws Exception {
        UpdateBundle best = null;
        String bestBase = null, lastError = null;
        for (Channel c : channels) {
            String base = resolve(c);
            try {
                byte[] m = get(base + "manifest.json", MANIFEST_MAX, null);
                byte[] sig = get(base + "manifest.sig", 4096, null);
                UpdateBundle b = UpdateBundle.parse(m, new String(sig, UpdateBundle.UTF8), key, pkg);
                if (best == null || b.build > best.build) {
                    best = b;
                    bestBase = base;
                }
            } catch (Exception e) {
                lastError = base + ": " + e;
            }
        }
        if (best == null) return new Object[]{"error", null, null, lastError};
        synchronized (this) {
            UpdateBundle s = stagedUpdate();
            int have = Math.max(currentBuild(), s != null ? s.build : 0);
            if (best.build <= have || bad.contains(best.build))
                return new Object[]{s != null ? "ready" : "none", s, null, null};
        }
        if (best.minNative > nativeCode) return new Object[]{"native", best, best.apk == null ? null : bestBase + best.apk, null};
        long total = 0;
        for (UpdateBundle.Entry e : best.files.values()) total += e.size;
        if (total > TOTAL_MAX) throw new IOException("bundle too large");
        deleteTree(tmp);
        if (!tmp.mkdirs()) throw new IOException("cannot create " + tmp);
        for (Map.Entry<String, UpdateBundle.Entry> e : best.files.entrySet()) {
            UpdateBundle.Entry want = e.getValue();
            byte[] data = reuse(e.getKey(), want);
            if (data == null) data = get(bestBase + e.getKey(), want.size, null);
            if (data.length != want.size || !UpdateBundle.sha256(data).equals(want.sha256))
                throw new IOException("checksum mismatch: " + e.getKey());
            write(new File(tmp, e.getKey()), data);
        }
        write(new File(tmp, "manifest.json"), best.raw);
        write(new File(tmp, "manifest.sig"), best.sigHex.getBytes(UpdateBundle.UTF8));
        synchronized (this) {
            deleteTree(staged);
            stagedBundle = null;
            stagedKnown = false;
            if (!tmp.renameTo(staged)) throw new IOException("cannot stage update");
            stagedBundle = best; // just verified file by file
            stagedKnown = true;
        }
        return new Object[]{"ready", best, null, null};
    }

    /** The commit-pinned base URL for a channel, or its branch URL when the commit cannot be resolved. */
    private static String resolve(Channel c) {
        if (c.api != null) {
            try {
                String sha = new String(get(c.api, 256, "application/vnd.github.sha"), UpdateBundle.UTF8).trim();
                if (sha.matches("[0-9a-f]{40}")) return c.template.replace("{ref}", sha);
            } catch (IOException ignored) {
            }
        }
        return c.template.replace("{ref}", c.ref);
    }

    /** An identical copy of a bundle file already on the phone (active update or APK), or null. */
    private byte[] reuse(String rel, UpdateBundle.Entry want) {
        try {
            UpdateBundle a = activeBundle;
            UpdateBundle.Entry have = a == null ? null : a.files.get(rel);
            if (have != null && have.sha256.equals(want.sha256)) {
                byte[] d = read(new File(active, rel), want.size);
                if (UpdateBundle.sha256(d).equals(want.sha256)) return d;
            }
            if (local != null) {
                byte[] d = local.read(rel, want.size);
                if (d != null && d.length == want.size && UpdateBundle.sha256(d).equals(want.sha256)) return d;
            }
        } catch (Exception ignored) {
        }
        return null;
    }

    private boolean usable(UpdateBundle b) {
        return b.minNative <= nativeCode && !bad.contains(b.build);
    }

    /** A bundle directory that verifies completely (signature, package, every file's size and hash), or null. */
    private UpdateBundle load(File dir) {
        try {
            File mf = new File(dir, "manifest.json"), sf = new File(dir, "manifest.sig");
            if (!mf.isFile() || !sf.isFile()) return null;
            UpdateBundle b = UpdateBundle.parse(read(mf, MANIFEST_MAX), new String(read(sf, 4096), UpdateBundle.UTF8), key, pkg);
            for (Map.Entry<String, UpdateBundle.Entry> e : b.files.entrySet()) {
                byte[] d = read(new File(dir, e.getKey()), e.getValue().size);
                if (d.length != e.getValue().size || !UpdateBundle.sha256(d).equals(e.getValue().sha256)) return null;
            }
            return b;
        } catch (Exception e) {
            return null;
        }
    }

    private synchronized void loadBad() {
        bad.clear();
        try {
            for (String s : new String(read(badFile, 4096), UpdateBundle.UTF8).split("\\s+"))
                if (!s.isEmpty()) bad.add(Integer.parseInt(s));
        } catch (Exception ignored) {
        }
    }

    private void saveBad() {
        StringBuilder b = new StringBuilder();
        for (int n : bad) b.append(n).append('\n');
        try {
            write(badFile, b.toString().getBytes(UpdateBundle.UTF8));
        } catch (IOException ignored) {
        }
    }

    private static byte[] get(String url, long limit, String accept) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        try {
            c.setConnectTimeout(8000);
            c.setReadTimeout(15000);
            c.setUseCaches(false);
            c.setInstanceFollowRedirects(true); // never crosses https → http
            c.setRequestProperty("User-Agent", "geuhae-yeoreum-updater");
            c.setRequestProperty("Cache-Control", "no-cache");
            if (accept != null) c.setRequestProperty("Accept", accept);
            int code = c.getResponseCode();
            if (code != 200) throw new IOException("HTTP " + code + " " + url);
            return readAll(c.getInputStream(), limit);
        } finally {
            c.disconnect();
        }
    }

    private static byte[] read(File f, long limit) throws IOException {
        InputStream in = new FileInputStream(f);
        try {
            return readAll(in, limit);
        } finally {
            in.close();
        }
    }

    static byte[] readAll(InputStream in, long limit) throws IOException {
        ByteArrayOutputStream out = new ByteArrayOutputStream();
        byte[] buf = new byte[16384];
        int n;
        while ((n = in.read(buf)) > 0) {
            out.write(buf, 0, n);
            if (out.size() > limit) throw new IOException("too large");
        }
        return out.toByteArray();
    }

    private static void write(File f, byte[] data) throws IOException {
        File p = f.getParentFile();
        if (p != null && !p.isDirectory() && !p.mkdirs()) throw new IOException("cannot create " + p);
        OutputStream o = new FileOutputStream(f);
        try {
            o.write(data);
        } finally {
            o.close();
        }
    }

    private static void deleteTree(File f) {
        File[] kids = f.listFiles();
        if (kids != null) for (File k : kids) deleteTree(k);
        f.delete();
    }
}
