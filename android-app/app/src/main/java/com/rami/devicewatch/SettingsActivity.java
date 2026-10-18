package com.rami.devicewatch;

import android.annotation.SuppressLint;
import android.app.Activity;
import android.content.Intent;
import android.net.Uri;
import android.os.Bundle;
import android.os.PowerManager;
import android.provider.Settings;
import android.text.InputType;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;
import android.widget.ScrollView;
import android.widget.Switch;
import android.widget.TextView;
import android.widget.Toast;

/** Connection settings + the phone-side permissions HyperOS needs. */
public class SettingsActivity extends Activity {
    private EditText server, topic, secret, token;
    private Switch live;

    @SuppressLint("BatteryLife")
    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        Prefs p = new Prefs(this);

        LinearLayout col = Ui.column(this);
        int pad = Ui.dp(this, 16);
        col.setPadding(pad, pad, pad, pad * 2);

        col.addView(Ui.text(this, "Settings", 24, Ui.TEXT, true));
        col.addView(Ui.text(this, "Use the same topic and secret as your laptops' config.json. "
                + "They are stored only on this phone.", 13, Ui.DIM, false));

        server = field(col, "ntfy server", p.server(), false);
        topic = field(col, "Topic", p.topic(), false);
        secret = field(col, "Secret", p.secret(), true);
        token = field(col, "Access token (only for a private ntfy server)", p.token(), true);

        live = new Switch(this);
        live.setText("Live notifications (phone + watch)");
        live.setTextColor(Ui.TEXT);
        live.setTextSize(15);
        live.setChecked(p.live());
        col.addView(live, Ui.fullWidth(this, 18));
        TextView hint = Ui.text(this, "Keeps one small connection open so events arrive instantly. "
                + "Turn off if you prefer to use the ntfy app for notifications.", 12, Ui.DIM, false);
        col.addView(hint);

        Button save = Ui.button(this, "Save", false);
        save.setBackground(Ui.round(this, Ui.BLUE, 0, 12));
        save.setTextSize(15);
        save.setOnClickListener(v -> save());
        col.addView(save, Ui.fullWidth(this, 20));

        col.addView(Ui.text(this, "Xiaomi / HyperOS (important)", 16, Ui.TEXT, true), Ui.fullWidth(this, 28));
        col.addView(Ui.text(this, "1. Allow background activity, or HyperOS will stop notifications.\n"
                + "2. In App info, enable Autostart.\n"
                + "3. In Mi Fitness → Notifications, enable DeviceWatch so alerts reach your watch.",
                13, Ui.DIM, false));

        Button battery = Ui.button(this, "1. Allow background activity", false);
        battery.setOnClickListener(v -> {
            PowerManager pm = (PowerManager) getSystemService(POWER_SERVICE);
            if (pm != null && pm.isIgnoringBatteryOptimizations(getPackageName())) {
                Toast.makeText(this, "Already allowed ✓", Toast.LENGTH_SHORT).show();
                return;
            }
            try {
                startActivity(new Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS,
                        Uri.parse("package:" + getPackageName())));
            } catch (Exception e) {
                startActivity(new Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS));
            }
        });
        col.addView(battery, Ui.fullWidth(this, 12));

        Button appInfo = Ui.button(this, "2. Open App info (Autostart, Battery saver)", false);
        appInfo.setOnClickListener(v -> startActivity(new Intent(
                Settings.ACTION_APPLICATION_DETAILS_SETTINGS, Uri.parse("package:" + getPackageName()))));
        col.addView(appInfo, Ui.fullWidth(this, 8));

        ScrollView scroll = new ScrollView(this);
        scroll.addView(col);
        setContentView(scroll);
    }

    private EditText field(LinearLayout parent, String label, String value, boolean hidden) {
        TextView l = Ui.text(this, label, 13, Ui.DIM, false);
        parent.addView(l, Ui.fullWidth(this, 14));
        EditText e = new EditText(this);
        e.setText(value);
        e.setSingleLine(true);
        e.setTextColor(Ui.TEXT);
        e.setHintTextColor(Ui.DIM);
        e.setTextSize(15);
        int p = Ui.dp(this, 12);
        e.setPadding(p, p, p, p);
        e.setBackground(Ui.round(this, 0xFF0C0E12, Ui.LINE, 10));
        e.setInputType(InputType.TYPE_CLASS_TEXT | InputType.TYPE_TEXT_FLAG_NO_SUGGESTIONS
                | (hidden ? InputType.TYPE_TEXT_VARIATION_PASSWORD : InputType.TYPE_TEXT_VARIATION_URI));
        parent.addView(e, Ui.fullWidth(this, 4));
        return e;
    }

    private void save() {
        String t = topic.getText().toString().trim();
        String s = secret.getText().toString().trim();
        if (t.isEmpty() || s.isEmpty()) {
            Toast.makeText(this, "Topic and secret are required", Toast.LENGTH_SHORT).show();
            return;
        }
        new Prefs(this).save(server.getText().toString().trim(), t, s,
                token.getText().toString().trim(), live.isChecked());
        stopService(new Intent(this, WatchService.class));   // reconnect with new settings
        WatchService.sync(this);
        Toast.makeText(this, "Saved", Toast.LENGTH_SHORT).show();
        finish();
    }
}
