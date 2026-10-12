import java.io.FileInputStream;
import java.io.InputStream;
import java.nio.file.Files;
import java.nio.file.Paths;
import java.security.KeyStore;
import java.security.PrivateKey;
import java.security.Signature;
import java.security.cert.Certificate;

/**
 * Signs a web-update manifest with the APK signing key (SHA256withRSA, hex output) and checks the result
 * against that key's certificate, the same check the app makes before accepting an update.
 * Usage: java SignUpdate.java KEYSTORE STOREPASS ALIAS manifest.json manifest.sig
 */
public class SignUpdate {
    public static void main(String[] a) throws Exception {
        KeyStore ks = KeyStore.getInstance("PKCS12");
        try (InputStream in = new FileInputStream(a[0])) {
            ks.load(in, a[1].toCharArray());
        }
        PrivateKey key = (PrivateKey) ks.getKey(a[2], a[1].toCharArray());
        Certificate cert = ks.getCertificate(a[2]);
        byte[] manifest = Files.readAllBytes(Paths.get(a[3]));

        Signature s = Signature.getInstance("SHA256withRSA");
        s.initSign(key);
        s.update(manifest);
        byte[] sig = s.sign();

        Signature v = Signature.getInstance("SHA256withRSA");
        v.initVerify(cert.getPublicKey());
        v.update(manifest);
        if (!v.verify(sig)) throw new IllegalStateException("signature does not verify");

        StringBuilder hex = new StringBuilder();
        for (byte b : sig) hex.append(String.format("%02x", b & 0xff));
        Files.write(Paths.get(a[4]), (hex + "\n").getBytes("US-ASCII"));
        System.out.println("signed " + a[3] + " (" + manifest.length + " bytes)");
    }
}
