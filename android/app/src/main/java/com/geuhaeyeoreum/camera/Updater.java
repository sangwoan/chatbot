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
import java.util.HashSet;
import java.util.Map;
import java.util.Set;

/**
 * Over-the-air updates for the web part of the app (the page, its filters and UI), so most changes reach an
 * installed app without a new APK. The Android shell itself is never replaced: an update that needs a newer
 * shell is only reported, with the APK published next to it.
 *
 * - A bundle is accepted only if manifest.json is signed by the APK's own signing key (see UpdateBundle),
 *   names this package, is newer than what is installed and every file matches its SHA-256 and size.
 * - It is downloaded into private storage (ota/tmp), moved to ota/staged, and becomes ota/active at the next
 *   prepare() (app start, or resume while the page is idle). Files not in the bundle still come from the APK.
 * - A bundle whose page never reports a good start is marked bad and dropped (markBadActive).
 *
 * Pure Java (java.net/java.io/java.security plus org.json), so it can be exercised off-device.
 */
final class Updater {
    interface Listener {
        /** state: "ready" (staged), "native" (needs a newer APK), "none" (up to date) or "error". Called on a worker thread. */
        void onResult(String state, UpdateBundle bundle, String apkUrl, String error);
    }

    private static final int MANIFEST_MAX = 64 * 1024;
    private static final long TOTAL_MAX = 24L << 20;

    private final File active, staged, tmp, badFile;
    private final String[] bases;
    private final PublicKey key;
    private final String pkg;
    private final int nativeCode, bundledBuild;
    private final Set<Integer> bad = new HashSet<>();
    private volatile UpdateBundle activeBundle;
    private boolean checking;

    Updater(File root, String[] bases, PublicKey key, String pkg, int nativeCode, int bundledBuild) {
        this.active = new File(root, "active");
        this.staged = new File(root, "staged");
        this.tmp = new File(root, "tmp");
        this.badFile = new File(root, "bad.txt");
        this.bases = bases;
        this.key = key;
        this.pkg = pkg;
        this.nativeCode = nativeCode;
        this.bundledBuild = bundledBuild;
        root.mkdirs();
    }

    /** Promotes a newer staged bundle and drops stale or bad ones. Returns true when a staged bundle became active. */
    synchronized boolean prepare() {
        loadBad();
        UpdateBundle a = load(active), s = load(staged);
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

    synchronized boolean stagedNewer() {
        UpdateBundle s = load(staged);
        return s != null && usable(s) && s.build > currentBuild();
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

    /** Looks for a newer bundle on a worker thread and stages it. At most one check runs at a time. */
    void check(final Listener l) {
        synchronized (this) {
            if (checking) return;
            checking = true;
        }
        Thread t = new Thread(new Runnable() {
            @Override
            public void run() {
                try {
                    runCheck(l);
                } catch (Throwable e) {
                    l.onResult("error", null, null, String.valueOf(e));
                } finally {
                    synchronized (Updater.this) {
                        checking = false;
                    }
                }
            }
        }, "geuhae-update");
        t.setDaemon(true);
        t.start();
    }

    private void runCheck(Listener l) throws Exception {
        UpdateBundle best = null;
        String bestBase = null, lastError = null;
        for (String base : bases) {
            try {
                byte[] m = get(base + "manifest.json", MANIFEST_MAX);
                byte[] sig = get(base + "manifest.sig", 4096);
                UpdateBundle b = UpdateBundle.parse(m, new String(sig, UpdateBundle.UTF8), key, pkg);
                if (best == null || b.build > best.build) {
                    best = b;
                    bestBase = base;
                }
            } catch (Exception e) {
                lastError = base + ": " + e;
            }
        }
        if (best == null) {
            l.onResult("error", null, null, lastError);
            return;
        }
        int have;
        synchronized (this) {
            UpdateBundle s = load(staged);
            have = Math.max(currentBuild(), s != null && usable(s) ? s.build : 0);
            if (best.build <= have || bad.contains(best.build)) {
                l.onResult(s != null && usable(s) && s.build > currentBuild() ? "ready" : "none", s, null, null);
                return;
            }
        }
        if (best.minNative > nativeCode) {
            l.onResult("native", best, best.apk == null ? null : bestBase + best.apk, null);
            return;
        }
        long total = 0;
        for (UpdateBundle.Entry e : best.files.values()) total += e.size;
        if (total > TOTAL_MAX) throw new IOException("bundle too large");
        deleteTree(tmp);
        if (!tmp.mkdirs()) throw new IOException("cannot create " + tmp);
        for (Map.Entry<String, UpdateBundle.Entry> e : best.files.entrySet()) {
            byte[] data = get(bestBase + e.getKey(), e.getValue().size);
            if (data.length != e.getValue().size || !UpdateBundle.sha256(data).equals(e.getValue().sha256))
                throw new IOException("checksum mismatch: " + e.getKey());
            write(new File(tmp, e.getKey()), data);
        }
        write(new File(tmp, "manifest.json"), best.raw);
        write(new File(tmp, "manifest.sig"), best.sigHex.getBytes(UpdateBundle.UTF8));
        synchronized (this) {
            deleteTree(staged);
            if (!tmp.renameTo(staged)) throw new IOException("cannot stage update");
        }
        l.onResult("ready", best, null, null);
    }

    private boolean usable(UpdateBundle b) {
        return b.minNative <= nativeCode && !bad.contains(b.build);
    }

    /** A bundle directory that verifies completely (signature, package, every file's size and hash), or null. */
    private UpdateBundle load(File dir) {
        try {
            File mf = new File(dir, "manifest.json"), sf = new File(dir, "manifest.sig");
            if (!mf.isFile() || !sf.isFile()) return null;
            UpdateBundle b = UpdateBundle.parse(read(mf, 64 * 1024), new String(read(sf, 4096), UpdateBundle.UTF8), key, pkg);
            for (Map.Entry<String, UpdateBundle.Entry> e : b.files.entrySet()) {
                byte[] d = read(new File(dir, e.getKey()), e.getValue().size);
                if (d.length != e.getValue().size || !UpdateBundle.sha256(d).equals(e.getValue().sha256)) return null;
            }
            return b;
        } catch (Exception e) {
            return null;
        }
    }

    private void loadBad() {
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

    private static byte[] get(String url, long limit) throws IOException {
        HttpURLConnection c = (HttpURLConnection) new URL(url).openConnection();
        try {
            c.setConnectTimeout(10000);
            c.setReadTimeout(20000);
            c.setUseCaches(false);
            c.setInstanceFollowRedirects(true);
            c.setRequestProperty("Cache-Control", "no-cache");
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

    private static byte[] readAll(InputStream in, long limit) throws IOException {
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
