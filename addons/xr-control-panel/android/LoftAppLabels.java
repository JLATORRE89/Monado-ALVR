import android.content.Context;
import android.content.pm.PackageManager;
import android.os.Looper;
import org.json.JSONObject;

/** Read installed application labels as the authorized ADB shell; installs no app. */
public final class LoftAppLabels {
    public static void main(String[] packages) throws Exception {
        Looper.prepareMainLooper();
        Class<?> thread = Class.forName("android.app.ActivityThread");
        Object instance = thread.getMethod("systemMain").invoke(null);
        Context context = (Context) thread.getMethod("getSystemContext").invoke(instance);
        PackageManager pm = context.getPackageManager();
        JSONObject labels = new JSONObject();
        for (String name : packages) {
            try {
                labels.put(name, pm.getApplicationInfo(name, 0).loadLabel(pm).toString());
            } catch (Exception ignored) { /* Host keeps the package name as a fallback. */ }
        }
        System.out.println(labels.toString());
    }
}
