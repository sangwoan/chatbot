package com.geuhaeyeoreum.camera;

import org.json.JSONObject;

import java.nio.charset.Charset;
import java.security.MessageDigest;
import java.security.PublicKey;
import java.util.Collections;
import java.util.Iterator;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.regex.Pattern;

/**
 * A web update as published by android/publish-update.sh: manifest.json plus manifest.sig, a hex
 * SHA256withRSA signature over the exact manifest bytes made with the key that signs the APK.
 * Pure Java (plus org.json), so it can be tested off-device.
 */
final class UpdateBundle {
    static final long MAX_FILE = 8L << 20;
    static final Charset UTF8 = Charset.forName("UTF-8");
    /** Relative paths of up to four segments, each starting with a letter or digit, so ".." can never appear as a segment. */
    private static final Pattern SAFE = Pattern.compile("[A-Za-z0-9][A-Za-z0-9._-]{0,63}(/[A-Za-z0-9][A-Za-z0-9._-]{0,63}){0,3}");
    private static final Pattern SHA = Pattern.compile("[0-9a-f]{64}");

    static final class Entry {
        final String sha256;
        final long size;

        Entry(String sha256, long size) {
            this.sha256 = sha256;
            this.size = size;
        }
    }

    final byte[] raw;
    final String sigHex;
    final int build;
    final int minNative;
    final String version;
    /** Relative name of an APK published next to the manifest, for updates that need a newer shell; may be null. */
    final String apk;
    final Map<String, Entry> files;

    private UpdateBundle(byte[] raw, String sigHex, JSONObject o) throws Exception {
        this.raw = raw;
        this.sigHex = sigHex;
        build = o.getInt("build");
        minNative = o.getInt("minNative");
        version = o.optString("version", String.valueOf(build));
        String a = o.optString("apk", "");
        apk = a.isEmpty() ? null : a;
        if (apk != null && !safe(apk)) throw new SecurityException("bad apk name");
        JSONObject f = o.getJSONObject("files");
        Map<String, Entry> m = new LinkedHashMap<>();
        Iterator<String> it = f.keys();
        while (it.hasNext()) {
            String name = it.next();
            JSONObject e = f.getJSONObject(name);
            String sha = e.getString("sha256");
            long size = e.getLong("size");
            if (!safe(name) || !SHA.matcher(sha).matches() || size <= 0 || size > MAX_FILE)
                throw new SecurityException("bad file entry " + name);
            m.put(name, new Entry(sha, size));
        }
        if (m.isEmpty() || build <= 0) throw new SecurityException("empty bundle");
        files = Collections.unmodifiableMap(m);
    }

    /** Verifies the signature and the package name, then parses. Throws on anything unexpected. */
    static UpdateBundle parse(byte[] manifest, String sigHex, PublicKey key, String pkg) throws Exception {
        String sig = sigHex == null ? "" : sigHex.trim();
        java.security.Signature v = java.security.Signature.getInstance("SHA256withRSA");
        v.initVerify(key);
        v.update(manifest);
        if (!v.verify(hex(sig))) throw new SecurityException("bad signature");
        JSONObject o = new JSONObject(new String(manifest, UTF8));
        if (!pkg.equals(o.optString("package"))) throw new SecurityException("bundle for another app");
        return new UpdateBundle(manifest, sig, o);
    }

    static boolean safe(String rel) {
        return rel != null && SAFE.matcher(rel).matches();
    }

    static String sha256(byte[] b) throws Exception {
        byte[] d = MessageDigest.getInstance("SHA-256").digest(b);
        StringBuilder s = new StringBuilder(64);
        for (byte x : d) s.append(String.format("%02x", x & 0xff));
        return s.toString();
    }

    static byte[] hex(String s) {
        if (s.length() % 2 != 0) throw new IllegalArgumentException("odd hex");
        byte[] out = new byte[s.length() / 2];
        for (int i = 0; i < out.length; i++) {
            int hi = Character.digit(s.charAt(2 * i), 16), lo = Character.digit(s.charAt(2 * i + 1), 16);
            if (hi < 0 || lo < 0) throw new IllegalArgumentException("not hex");
            out[i] = (byte) ((hi << 4) | lo);
        }
        return out;
    }
}
