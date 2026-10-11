package com.geuhaeyeoreum.camera;

import android.Manifest;
import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.ClipData;
import android.content.ContentResolver;
import android.content.ContentValues;
import android.content.Intent;
import android.content.SharedPreferences;
import android.content.pm.ApplicationInfo;
import android.content.pm.PackageManager;
import android.database.Cursor;
import android.graphics.Bitmap;
import android.graphics.Canvas;
import android.graphics.Color;
import android.graphics.ColorFilter;
import android.graphics.Paint;
import android.graphics.PixelFormat;
import android.graphics.Rect;
import android.graphics.drawable.Drawable;
import android.media.MediaScannerConnection;
import android.net.Uri;
import android.os.Build;
import android.os.Bundle;
import android.os.Environment;
import android.os.Handler;
import android.os.Looper;
import android.os.SystemClock;
import android.os.VibrationEffect;
import android.os.Vibrator;
import android.provider.MediaStore;
import android.provider.Settings;
import android.util.Base64;
import android.util.Log;
import android.view.HapticFeedbackConstants;
import android.view.KeyEvent;
import android.view.View;
import android.view.ViewGroup;
import android.view.Window;
import android.view.WindowInsets;
import android.view.WindowInsetsController;
import android.view.WindowManager;
import android.webkit.ConsoleMessage;
import android.webkit.RenderProcessGoneDetail;
import android.webkit.GeolocationPermissions;
import android.webkit.JavascriptInterface;
import android.webkit.PermissionRequest;
import android.webkit.ValueCallback;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

import java.io.ByteArrayInputStream;
import java.io.File;
import java.io.FileOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.io.OutputStream;
import java.util.ArrayDeque;
import java.util.HashMap;
import java.util.Locale;
import java.util.Map;

/**
 * Hosts the web camera (assets/www) in a full-screen WebView.
 * The page is served from https://appassets.androidplatform.net/assets/ so it is a secure
 * context (camera, IndexedDB, localStorage) without needing androidx.webkit.
 */
public class MainActivity extends Activity {
    private static final String TAG = "Geuhae";
    static final String HOST = "appassets.androidplatform.net";
    static final String START_URL = "https://" + HOST + "/assets/index.html";
    static final String ALBUM_DIR = "그해여름";

    private static final int REQ_CAMERA_FOR_PAGE = 1;
    private static final int REQ_CAMERA_DIRECT = 2;
    private static final int REQ_STORAGE = 4;
    private static final int REQ_FILES = 10;
    private static final int MAX_PICK = 30;

    /** Android drops a second permission request while a dialog is open, so requests wait their turn. */
    private final ArrayDeque<Object[]> askQueue = new ArrayDeque<>();
    private boolean asking = false;
    private long backAskedAt = 0;
    /** Camera dialog bookkeeping, to tell "don't ask again" apart from a dismissed dialog. */
    private boolean camRationaleBefore = false;
    private long camAskedAt = 0;
    /** One storage dialog at a time (Android 9 and below); the page queues the photos meanwhile. */
    private boolean storageAsking = false;

    private final Handler ui = new Handler(Looper.getMainLooper());
    private FrameLayout root;
    private WebView web;
    private BarsDrawable bars;
    private boolean darkIconsTop = true, darkIconsBottom = true;

    private PermissionRequest pendingMedia;
    private ValueCallback<Uri[]> pendingFiles;
    /** Host of the page currently loaded; the bridge only acts for our own origin. */
    private volatile String pageHost = HOST; // seeded: page scripts can call the bridge before onPageStarted arrives
    /** Set by the page while the live viewfinder is on screen: volume keys fire the shutter. */
    private volatile boolean volumeShutter = false;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        int start = 0xFFA3D2DE;
        bars = new BarsDrawable(start, start);
        root = new FrameLayout(this);
        root.setBackground(bars);
        web = new WebView(this);
        web.setBackgroundColor(Color.rgb(7, 9, 12));
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);
        setupWindow();
        setupWebView();
        web.loadUrl(START_URL);
    }

    // ───────── window: edge-to-edge with our own insets so system bars show the camera body colour
    private void setupWindow() {
        Window w = getWindow();
        if (Build.VERSION.SDK_INT >= 30) {
            w.setDecorFitsSystemWindows(false);
            w.setStatusBarColor(Color.TRANSPARENT);
            w.setNavigationBarColor(Color.TRANSPARENT);
            w.setNavigationBarContrastEnforced(false);
            root.setOnApplyWindowInsetsListener(new View.OnApplyWindowInsetsListener() {
                @Override
                public WindowInsets onApplyWindowInsets(View v, WindowInsets insets) {
                    android.graphics.Insets i = insets.getInsets(WindowInsets.Type.systemBars()
                            | WindowInsets.Type.displayCutout() | WindowInsets.Type.ime());
                    v.setPadding(i.left, i.top, i.right, i.bottom);
                    return WindowInsets.CONSUMED;
                }
            });
        }
        applyBars();
    }

    private void applyBars() {
        bars.invalidateSelf();
        Window w = getWindow();
        if (Build.VERSION.SDK_INT >= 30) {
            WindowInsetsController c = w.getInsetsController();
            if (c != null) {
                int s = WindowInsetsController.APPEARANCE_LIGHT_STATUS_BARS;
                int n = WindowInsetsController.APPEARANCE_LIGHT_NAVIGATION_BARS;
                c.setSystemBarsAppearance((darkIconsTop ? s : 0) | (darkIconsBottom ? n : 0), s | n);
            }
        } else {
            w.setStatusBarColor(bars.top);
            // below API 26 the navigation bar cannot have dark icons, so a light body colour would hide them
            w.setNavigationBarColor(Build.VERSION.SDK_INT >= 26 || !darkIconsBottom ? bars.bottom : Color.BLACK);
            View d = w.getDecorView();
            int f = d.getSystemUiVisibility();
            f = darkIconsTop ? f | View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR : f & ~View.SYSTEM_UI_FLAG_LIGHT_STATUS_BAR;
            if (Build.VERSION.SDK_INT >= 26) {
                f = darkIconsBottom ? f | View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR : f & ~View.SYSTEM_UI_FLAG_LIGHT_NAVIGATION_BAR;
            }
            d.setSystemUiVisibility(f);
        }
    }

    // ───────── WebView
    private void setupWebView() {
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setMediaPlaybackRequiresUserGesture(false);
        s.setAllowFileAccess(false);
        s.setMixedContentMode(WebSettings.MIXED_CONTENT_NEVER_ALLOW);
        s.setSupportMultipleWindows(false);
        s.setJavaScriptCanOpenWindowsAutomatically(false);
        s.setCacheMode(WebSettings.LOAD_NO_CACHE);
        s.setSupportZoom(false);
        s.setBuiltInZoomControls(false);
        s.setDisplayZoomControls(false);
        s.setTextZoom(100);
        s.setGeolocationEnabled(false); // no location permission: fewer sensitive permissions, nothing for scanners to misread
        if ((getApplicationInfo().flags & ApplicationInfo.FLAG_DEBUGGABLE) != 0) {
            WebView.setWebContentsDebuggingEnabled(true);
        }
        web.setOverScrollMode(View.OVER_SCROLL_NEVER);
        web.setVerticalScrollBarEnabled(false);
        web.setHorizontalScrollBarEnabled(false);
        web.addJavascriptInterface(new Bridge(), "GeuhaeNative");
        web.setWebViewClient(new AssetClient());
        web.setWebChromeClient(new Chrome());
    }

    private static String hostOf(String url) {
        try {
            String h = Uri.parse(url).getHost();
            return h == null ? "" : h;
        } catch (Exception e) {
            return "";
        }
    }

    private static boolean isOurs(Uri u) {
        return u != null && "https".equals(u.getScheme()) && HOST.equals(u.getHost());
    }

    private final class AssetClient extends WebViewClient {
        @Override
        public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
            Uri u = req.getUrl();
            if (!isOurs(u)) {
                String sc = u.getScheme();
                return "http".equals(sc) || "https".equals(sc) ? notFound() : null;
            }
            String path = u.getPath();
            if (path == null || !path.startsWith("/assets/")) return notFound();
            String rel = path.substring("/assets/".length());
            if (rel.isEmpty() || rel.endsWith("/")) rel = rel + "index.html";
            if (rel.contains("..")) return notFound();
            try {
                InputStream in = getAssets().open("www/" + rel);
                String mime = mimeOf(rel);
                WebResourceResponse r = new WebResourceResponse(mime, mime.startsWith("text/") || mime.endsWith("javascript") || mime.endsWith("json") || mime.endsWith("svg+xml") ? "utf-8" : null, in);
                Map<String, String> h = new HashMap<>();
                h.put("Cache-Control", "no-cache");
                r.setResponseHeaders(h);
                return r;
            } catch (IOException e) {
                return notFound();
            }
        }

        @Override
        public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
            Uri u = req.getUrl();
            if (isOurs(u)) return false;
            try {
                startActivity(new Intent(Intent.ACTION_VIEW, u));
            } catch (ActivityNotFoundException ignored) {
            }
            return true;
        }

        @Override
        public void onPageStarted(WebView view, String url, Bitmap favicon) {
            pageHost = hostOf(url);
        }

        @Override
        public boolean onRenderProcessGone(WebView view, RenderProcessGoneDetail detail) {
            // the renderer crashed or was killed for memory: rebuild instead of letting the app die
            if (web == view) {
                root.removeView(web);
                web.destroy();
                web = null;
            }
            recreate();
            return true;
        }
    }

    private static WebResourceResponse notFound() {
        WebResourceResponse r = new WebResourceResponse("text/plain", "utf-8", new ByteArrayInputStream(new byte[0]));
        r.setStatusCodeAndReasonPhrase(404, "Not Found");
        return r;
    }

    static String mimeOf(String name) {
        String n = name.toLowerCase(Locale.ROOT);
        if (n.endsWith(".html")) return "text/html";
        if (n.endsWith(".js") || n.endsWith(".mjs")) return "application/javascript";
        if (n.endsWith(".css")) return "text/css";
        if (n.endsWith(".svg")) return "image/svg+xml";
        if (n.endsWith(".png")) return "image/png";
        if (n.endsWith(".jpg") || n.endsWith(".jpeg")) return "image/jpeg";
        if (n.endsWith(".webp")) return "image/webp";
        if (n.endsWith(".woff2")) return "font/woff2";
        if (n.endsWith(".woff")) return "font/woff";
        if (n.endsWith(".ttf")) return "font/ttf";
        if (n.endsWith(".json")) return "application/json";
        if (n.endsWith(".webmanifest")) return "application/manifest+json";
        if (n.endsWith(".txt")) return "text/plain";
        return "application/octet-stream";
    }

    private final class Chrome extends WebChromeClient {
        @Override
        public void onPermissionRequest(final PermissionRequest r) {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    Uri o = r.getOrigin();
                    boolean video = false;
                    for (String res : r.getResources()) {
                        if (PermissionRequest.RESOURCE_VIDEO_CAPTURE.equals(res)) video = true;
                    }
                    if (!isOurs(o) || !video) {
                        r.deny();
                        return;
                    }
                    if (has(Manifest.permission.CAMERA)) {
                        r.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
                    } else {
                        if (pendingMedia != null) pendingMedia.deny();
                        pendingMedia = r;
                        askCamera(REQ_CAMERA_FOR_PAGE);
                    }
                }
            });
        }

        @Override
        public void onPermissionRequestCanceled(PermissionRequest r) {
            if (pendingMedia == r) pendingMedia = null;
        }

        @Override
        public boolean onShowFileChooser(WebView view, ValueCallback<Uri[]> cb, FileChooserParams params) {
            if (pendingFiles != null) pendingFiles.onReceiveValue(null);
            pendingFiles = cb;
            boolean multiple = params != null && params.getMode() == FileChooserParams.MODE_OPEN_MULTIPLE;
            if (Build.VERSION.SDK_INT >= 33) {
                Intent picker = new Intent(MediaStore.ACTION_PICK_IMAGES);
                picker.setType("image/*");
                if (multiple) picker.putExtra(MediaStore.EXTRA_PICK_IMAGES_MAX, Math.min(MAX_PICK, MediaStore.getPickImagesMaxLimit()));
                try {
                    startActivityForResult(picker, REQ_FILES);
                    return true;
                } catch (ActivityNotFoundException ignored) {
                }
            }
            Intent pick = new Intent(Intent.ACTION_GET_CONTENT);
            pick.addCategory(Intent.CATEGORY_OPENABLE);
            pick.setType("image/*");
            if (multiple) pick.putExtra(Intent.EXTRA_ALLOW_MULTIPLE, true);
            try {
                startActivityForResult(Intent.createChooser(pick, "사진 고르기"), REQ_FILES);
            } catch (ActivityNotFoundException e) {
                pendingFiles = null;
                cb.onReceiveValue(null);
            }
            return true;
        }

        @Override
        public void onGeolocationPermissionsShowPrompt(String origin, GeolocationPermissions.Callback cb) {
            cb.invoke(origin, false, false); // the app does not hold a location permission
        }

        @Override
        public boolean onConsoleMessage(ConsoleMessage m) {
            Log.d(TAG, m.message() + " (" + m.sourceId() + ":" + m.lineNumber() + ")");
            return true;
        }
    }

    // ───────── permissions & results
    private boolean has(String perm) {
        return checkSelfPermission(perm) == PackageManager.PERMISSION_GRANTED;
    }

    private SharedPreferences prefs() {
        return getSharedPreferences("geuhae", MODE_PRIVATE);
    }

    private void askCamera(int req) {
        prefs().edit().putBoolean("askedCamera", true).apply();
        ask(new String[]{Manifest.permission.CAMERA}, req);
    }

    private void ask(String[] perms, int req) {
        askQueue.add(new Object[]{perms, req});
        if (!asking) askNext();
    }

    private void askNext() {
        Object[] next = askQueue.poll();
        asking = next != null;
        if (next == null) return;
        int req = (Integer) next[1];
        if (req == REQ_CAMERA_FOR_PAGE || req == REQ_CAMERA_DIRECT) {
            camRationaleBefore = shouldShowRequestPermissionRationale(Manifest.permission.CAMERA);
            camAskedAt = SystemClock.uptimeMillis();
        }
        requestPermissions((String[]) next[0], req);
    }

    @Override
    public void onRequestPermissionsResult(int req, String[] perms, int[] results) {
        ui.post(new Runnable() {
            @Override
            public void run() {
                askNext();
            }
        });
        boolean all = results.length > 0;
        for (int r : results) {
            if (r != PackageManager.PERMISSION_GRANTED) all = false;
        }
        if (req == REQ_CAMERA_FOR_PAGE || req == REQ_CAMERA_DIRECT) {
            rememberCameraAnswer(all, results.length > 0);
            PermissionRequest p = pendingMedia;
            pendingMedia = null;
            if (p != null) {
                if (all) p.grant(new String[]{PermissionRequest.RESOURCE_VIDEO_CAPTURE});
                else p.deny();
            }
            notifyPage("camera", all);
        } else if (req == REQ_STORAGE) {
            storageAsking = false;
            // empty results: the request was cancelled (e.g. relaunched from the launcher), not refused
            notifyPage(results.length == 0 ? "storage-cancel" : "storage", all);
        }
    }

    /**
     * Only Settings can bring the camera back once the user picked "don't ask again" (or Android 11+ stopped asking after two
     * refusals). Rationale flips from true to false at that moment, and a dialog that was never shown answers almost at once.
     * A dismissed or cancelled dialog does neither, so it stays "denied" and the page may ask again.
     */
    private void rememberCameraAnswer(boolean granted, boolean answered) {
        SharedPreferences.Editor e = prefs().edit();
        if (granted) {
            e.remove("cameraBlocked");
        } else if (answered && !shouldShowRequestPermissionRationale(Manifest.permission.CAMERA)
                && (camRationaleBefore || SystemClock.uptimeMillis() - camAskedAt < 400)) {
            e.putBoolean("cameraBlocked", true);
        }
        e.apply();
    }

    private void notifyPage(String what, boolean granted) {
        js("window.geuhaeOnPermission&&window.geuhaeOnPermission('" + what + "'," + granted + ")");
    }

    private void js(final String code) {
        ui.post(new Runnable() {
            @Override
            public void run() {
                if (web != null) web.evaluateJavascript(code, null);
            }
        });
    }

    @Override
    protected void onActivityResult(int req, int res, Intent data) {
        if (req != REQ_FILES) {
            super.onActivityResult(req, res, data);
            return;
        }
        ValueCallback<Uri[]> cb = pendingFiles;
        pendingFiles = null;
        if (cb == null) return;
        Uri[] out = null;
        if (res == RESULT_OK && data != null) {
            ClipData clip = data.getClipData();
            if (clip != null && clip.getItemCount() > 0) {
                out = new Uri[clip.getItemCount()];
                for (int i = 0; i < out.length; i++) out[i] = clip.getItemAt(i).getUri();
            } else if (data.getData() != null) {
                out = new Uri[]{data.getData()};
            }
        }
        cb.onReceiveValue(out);
    }

    // ───────── volume keys work as a shutter button while the viewfinder is showing
    @Override
    public boolean onKeyDown(int keyCode, KeyEvent event) {
        if (volumeShutter && (keyCode == KeyEvent.KEYCODE_VOLUME_UP || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN)) {
            if (event.getRepeatCount() == 0 && web != null) {
                web.evaluateJavascript("window.geuhaeShutter&&window.geuhaeShutter()", null);
            }
            return true;
        }
        return super.onKeyDown(keyCode, event);
    }

    @Override
    public boolean onKeyUp(int keyCode, KeyEvent event) {
        if (volumeShutter && (keyCode == KeyEvent.KEYCODE_VOLUME_UP || keyCode == KeyEvent.KEYCODE_VOLUME_DOWN)) return true;
        return super.onKeyUp(keyCode, event);
    }

    // ───────── back button: the page closes its own sheets first
    @Override
    @SuppressWarnings("deprecation")
    public void onBackPressed() {
        if (web == null) {
            super.onBackPressed();
            return;
        }
        long now = System.currentTimeMillis();
        if (backAskedAt != 0 && now - backAskedAt > 1500) {
            moveTaskToBack(true);
            return;
        }
        backAskedAt = now;
        web.evaluateJavascript("(function(){try{return !!(window.geuhaeOnBack&&window.geuhaeOnBack())}catch(e){return false}})()", new ValueCallback<String>() {
            @Override
            public void onReceiveValue(String v) {
                backAskedAt = 0;
                // keep the WebView alive: photos may still be developing in the page's queue
                if (!"true".equals(v)) moveTaskToBack(true);
            }
        });
    }

    // ───────── lifecycle: release the camera while in the background
    @Override
    protected void onPause() {
        if (web != null) {
            web.evaluateJavascript("window.geuhaeOnPause&&window.geuhaeOnPause()", null);
            web.onPause();
        }
        super.onPause();
    }

    @Override
    protected void onResume() {
        super.onResume();
        if (web != null) {
            web.onResume();
            web.evaluateJavascript("window.geuhaeOnResume&&window.geuhaeOnResume()", null);
        }
    }

    @Override
    protected void onStart() {
        super.onStart();
        if (web != null) web.resumeTimers();
    }

    @Override
    protected void onStop() {
        if (web != null) web.pauseTimers();
        super.onStop();
    }

    @Override
    protected void onDestroy() {
        if (pendingMedia != null) {
            pendingMedia.deny();
            pendingMedia = null;
        }
        if (pendingFiles != null) {
            pendingFiles.onReceiveValue(null);
            pendingFiles = null;
        }
        if (web != null) {
            root.removeView(web);
            web.destroy();
            web = null;
        }
        super.onDestroy();
    }

    // ───────── gallery
    private static final class NeedPermission extends Exception {
    }

    private static String safeName(String name) {
        String n = name == null ? "" : name.replaceAll("[^A-Za-z0-9._-]", "_");
        if (!n.toLowerCase(Locale.ROOT).endsWith(".jpg")) n = n + ".jpg";
        return n.length() > 120 ? n.substring(n.length() - 120) : n;
    }

    private Uri writeToGallery(byte[] data, String name, long takenMs) throws Exception {
        ContentResolver cr = getContentResolver();
        if (Build.VERSION.SDK_INT >= 29) {
            ContentValues v = new ContentValues();
            v.put(MediaStore.MediaColumns.DISPLAY_NAME, name);
            v.put(MediaStore.MediaColumns.MIME_TYPE, "image/jpeg");
            v.put(MediaStore.MediaColumns.RELATIVE_PATH, Environment.DIRECTORY_PICTURES + "/" + ALBUM_DIR);
            if (takenMs > 0) v.put(MediaStore.MediaColumns.DATE_TAKEN, takenMs);
            v.put(MediaStore.MediaColumns.IS_PENDING, 1);
            Uri uri = cr.insert(MediaStore.Images.Media.getContentUri(MediaStore.VOLUME_EXTERNAL_PRIMARY), v);
            if (uri == null) throw new IOException("MediaStore insert failed");
            try (OutputStream os = cr.openOutputStream(uri)) {
                if (os == null) throw new IOException("no output stream");
                os.write(data);
            } catch (IOException e) {
                cr.delete(uri, null, null);
                throw e;
            }
            ContentValues done = new ContentValues();
            done.put(MediaStore.MediaColumns.IS_PENDING, 0);
            cr.update(uri, done, null, null);
            return uri;
        }
        if (!has(Manifest.permission.WRITE_EXTERNAL_STORAGE)) throw new NeedPermission();
        File dir = new File(Environment.getExternalStoragePublicDirectory(Environment.DIRECTORY_PICTURES), ALBUM_DIR);
        if (!dir.isDirectory() && !dir.mkdirs()) throw new IOException("cannot create " + dir);
        String base = name.substring(0, name.length() - 4);
        File f = new File(dir, name);
        for (int i = 1; !f.createNewFile(); i++) f = new File(dir, base + "_" + i + ".jpg");
        try (FileOutputStream os = new FileOutputStream(f)) {
            os.write(data);
        }
        ContentValues v = new ContentValues();
        v.put(MediaStore.MediaColumns.DATA, f.getAbsolutePath());
        v.put(MediaStore.MediaColumns.DISPLAY_NAME, f.getName());
        v.put(MediaStore.MediaColumns.MIME_TYPE, "image/jpeg");
        if (takenMs > 0) v.put(MediaStore.Images.ImageColumns.DATE_TAKEN, takenMs);
        Uri uri = null;
        try {
            uri = cr.insert(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, v);
        } catch (Exception e) {
            Log.w(TAG, "MediaStore insert (legacy) failed", e);
        }
        MediaScannerConnection.scanFile(this, new String[]{f.getAbsolutePath()}, new String[]{"image/jpeg"}, null);
        if (uri == null) throw new IOException("saved but not indexed");
        return uri;
    }

    /** JavaScript bridge. Methods run on the WebView's background thread. */
    private final class Bridge {
        private boolean trusted() {
            return HOST.equals(pageHost);
        }

        @JavascriptInterface
        public boolean isNative() {
            return true;
        }

        @JavascriptInterface
        public String version() {
            try {
                return getPackageManager().getPackageInfo(getPackageName(), 0).versionName;
            } catch (Exception e) {
                return "";
            }
        }

        /** Saves a JPEG into Pictures/그해여름. Returns a content:// uri, "need-permission" or "". */
        @JavascriptInterface
        public String saveImage(String base64, String fileName, double takenMs) {
            if (!trusted() || base64 == null || base64.isEmpty()) return "";
            try {
                byte[] bytes = Base64.decode(base64, Base64.DEFAULT);
                return writeToGallery(bytes, safeName(fileName), (long) takenMs).toString();
            } catch (NeedPermission e) {
                ui.post(new Runnable() {
                    @Override
                    public void run() {
                        if (storageAsking) return;
                        storageAsking = true;
                        ask(new String[]{Manifest.permission.WRITE_EXTERNAL_STORAGE}, REQ_STORAGE);
                    }
                });
                return "need-permission";
            } catch (Throwable e) {
                Log.w(TAG, "saveImage failed", e);
                return "";
            }
        }

        /** True when saveImage can write without asking (Android 10+, or storage already granted). */
        @JavascriptInterface
        public boolean canSaveToGallery() {
            return Build.VERSION.SDK_INT >= 29 || has(Manifest.permission.WRITE_EXTERNAL_STORAGE);
        }

        @JavascriptInterface
        public boolean shareImage(String contentUri) {
            if (!trusted() || contentUri == null || !contentUri.startsWith("content://")) return false;
            final Uri u = Uri.parse(contentUri);
            // the user may have deleted it in their gallery app; the page then saves a fresh copy
            try (Cursor c = getContentResolver().query(u, new String[]{MediaStore.MediaColumns._ID}, null, null, null)) {
                if (c == null || !c.moveToFirst()) return false;
            } catch (Exception e) {
                return false;
            }
            ui.post(new Runnable() {
                @Override
                public void run() {
                    Intent send = new Intent(Intent.ACTION_SEND);
                    send.setType("image/jpeg");
                    send.putExtra(Intent.EXTRA_STREAM, u);
                    send.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION);
                    try {
                        startActivity(Intent.createChooser(send, "사진 보내기"));
                    } catch (ActivityNotFoundException ignored) {
                    }
                }
            });
            return true;
        }

        @JavascriptInterface
        @SuppressWarnings("deprecation")
        public void vibrate(int ms) {
            Vibrator v = (Vibrator) getSystemService(VIBRATOR_SERVICE);
            if (v == null || !v.hasVibrator()) return;
            int d = Math.max(1, Math.min(ms, 300));
            if (Build.VERSION.SDK_INT >= 26) v.vibrate(VibrationEffect.createOneShot(d, VibrationEffect.DEFAULT_AMPLITUDE));
            else v.vibrate(d);
        }

        /** "tick" (dial detents, toggles), "confirm" (shutter), "reject" (refused action). Follows the system haptics setting. */
        @JavascriptInterface
        public void haptic(final String kind) {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    if (web == null) return;
                    int c;
                    if ("confirm".equals(kind)) c = Build.VERSION.SDK_INT >= 30 ? HapticFeedbackConstants.CONFIRM : HapticFeedbackConstants.VIRTUAL_KEY;
                    else if ("reject".equals(kind)) c = Build.VERSION.SDK_INT >= 30 ? HapticFeedbackConstants.REJECT : HapticFeedbackConstants.LONG_PRESS;
                    else c = Build.VERSION.SDK_INT >= 27 ? HapticFeedbackConstants.TEXT_HANDLE_MOVE : HapticFeedbackConstants.CLOCK_TICK;
                    web.performHapticFeedback(c);
                }
            });
        }

        @JavascriptInterface
        public void setVolumeShutter(boolean on) {
            volumeShutter = on && trusted();
        }

        @JavascriptInterface
        public void keepScreenOn(final boolean on) {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    if (on) getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                    else getWindow().clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
                }
            });
        }

        /** Colours the status bar (top) and navigation bar (bottom) to match the camera body. */
        @JavascriptInterface
        public void setBarColors(String top, String bottom, boolean darkIconsOnTop, boolean darkIconsOnBottom) {
            final int t, b;
            try {
                t = Color.parseColor(top);
                b = Color.parseColor(bottom);
            } catch (Exception e) {
                return;
            }
            ui.post(new Runnable() {
                @Override
                public void run() {
                    bars.top = t;
                    bars.bottom = b;
                    darkIconsTop = darkIconsOnTop;
                    darkIconsBottom = darkIconsOnBottom;
                    applyBars();
                }
            });
        }

        /** "granted", "prompt" (never asked), "denied" (can ask again) or "blocked" (only Settings can fix it). */
        @JavascriptInterface
        public String cameraPermission() {
            if (has(Manifest.permission.CAMERA)) {
                if (prefs().getBoolean("cameraBlocked", false)) prefs().edit().remove("cameraBlocked").apply();
                return "granted";
            }
            if (shouldShowRequestPermissionRationale(Manifest.permission.CAMERA)) return "denied";
            if (prefs().getBoolean("cameraBlocked", false)) return "blocked";
            return prefs().getBoolean("askedCamera", false) ? "denied" : "prompt";
        }

        @JavascriptInterface
        public void requestCamera() {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    askCamera(REQ_CAMERA_DIRECT);
                }
            });
        }

        @JavascriptInterface
        public void openAppSettings() {
            ui.post(new Runnable() {
                @Override
                public void run() {
                    try {
                        startActivity(new Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.fromParts("package", getPackageName(), null)));
                    } catch (ActivityNotFoundException ignored) {
                    }
                }
            });
        }
    }

    /** Paints the area behind the status bar and the navigation bar in two colours. */
    private static final class BarsDrawable extends Drawable {
        int top, bottom;
        private final Paint paint = new Paint();

        BarsDrawable(int top, int bottom) {
            this.top = top;
            this.bottom = bottom;
        }

        @Override
        public void draw(Canvas c) {
            Rect r = getBounds();
            int mid = r.top + r.height() / 2;
            paint.setColor(top);
            c.drawRect(r.left, r.top, r.right, mid, paint);
            paint.setColor(bottom);
            c.drawRect(r.left, mid, r.right, r.bottom, paint);
        }

        @Override
        public void setAlpha(int alpha) {
        }

        @Override
        public void setColorFilter(ColorFilter cf) {
        }

        @Override
        @SuppressWarnings("deprecation")
        public int getOpacity() {
            return PixelFormat.OPAQUE;
        }
    }
}
