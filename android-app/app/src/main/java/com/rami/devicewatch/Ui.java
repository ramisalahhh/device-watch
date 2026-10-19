package com.rami.devicewatch;

import android.content.Context;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.util.TypedValue;
import android.view.Gravity;
import android.view.View;
import android.widget.Button;
import android.widget.LinearLayout;
import android.widget.TextView;

/** Small helpers so the UI can be built in code (no layout XML, no libraries). */
final class Ui {
    static final int BG = 0xFF0F1115, CARD = 0xFF181B22, LINE = 0xFF262A34, BTN = 0xFF232733,
            TEXT = 0xFFE8EAF0, DIM = 0xFF8B91A1, GREEN = 0xFF2ECC71, AMBER = 0xFFF5A623,
            RED = 0xFFFF5B5B, BLUE = 0xFF4C8DFF, DANGER = 0xFF3A1D22, DANGER_LINE = 0xFF5A2A31;

    private Ui() {}

    static int dp(Context c, float v) {
        return Math.round(TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v,
                c.getResources().getDisplayMetrics()));
    }

    static GradientDrawable round(Context c, int fill, int stroke, float radiusDp) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(fill);
        g.setCornerRadius(dp(c, radiusDp));
        if (stroke != 0) g.setStroke(dp(c, 1), stroke);
        return g;
    }

    static TextView text(Context c, String s, float sp, int color, boolean bold) {
        TextView t = new TextView(c);
        t.setText(s);
        t.setTextSize(TypedValue.COMPLEX_UNIT_SP, sp);
        t.setTextColor(color);
        if (bold) t.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return t;
    }

    static Button button(Context c, String label, boolean danger) {
        Button b = new Button(c);
        b.setText(label);
        b.setAllCaps(false);
        b.setTextColor(TEXT);
        b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 13);
        b.setGravity(Gravity.CENTER);
        b.setStateListAnimator(null);
        b.setMinHeight(0);
        b.setMinimumHeight(0);
        int p = dp(c, 10);
        b.setPadding(dp(c, 4), p, dp(c, 4), p);
        b.setBackground(danger ? round(c, DANGER, DANGER_LINE, 12) : round(c, BTN, LINE, 12));
        return b;
    }

    static LinearLayout.LayoutParams weight(Context c, float marginDp) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(0,
                LinearLayout.LayoutParams.WRAP_CONTENT, 1f);
        lp.setMargins(dp(c, marginDp), 0, dp(c, marginDp), 0);
        return lp;
    }

    static LinearLayout row(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.HORIZONTAL);
        return l;
    }

    static LinearLayout column(Context c) {
        LinearLayout l = new LinearLayout(c);
        l.setOrientation(LinearLayout.VERTICAL);
        return l;
    }

    static LinearLayout.LayoutParams fullWidth(Context c, float topDp) {
        LinearLayout.LayoutParams lp = new LinearLayout.LayoutParams(
                LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT);
        lp.topMargin = dp(c, topDp);
        return lp;
    }

    static String duration(long sec) {
        long h = sec / 3600, m = (sec % 3600) / 60;
        return h > 0 ? h + "h " + m + "m" : m + "m";
    }

    /** "CPU 34% · RAM 61% · GPU 80% · 🌡 72°C / 65°C" (only the parts we know). */
    static String stats(org.json.JSONObject hb) {
        StringBuilder b = new StringBuilder();
        if (hb.has("cpu") && !hb.isNull("cpu")) b.append("CPU ").append(hb.optInt("cpu")).append("%");
        if (hb.has("ram") && !hb.isNull("ram")) sep(b).append("RAM ").append(hb.optInt("ram")).append("%");
        if (hb.has("gpu") && !hb.isNull("gpu")) sep(b).append("GPU ").append(hb.optInt("gpu")).append("%");
        String ct = hb.isNull("ct") ? null : hb.optString("ct", null);
        String gt = hb.isNull("gt") ? null : hb.optString("gt", null);
        if (ct != null || gt != null) {
            sep(b).append("🌡 ");
            if (ct != null) b.append(ct).append("°C");
            if (ct != null && gt != null) b.append(" / ");
            if (gt != null) b.append(gt).append("°C");
        }
        return b.toString();
    }

    private static StringBuilder sep(StringBuilder b) {
        if (b.length() > 0) b.append(" · ");
        return b;
    }

    /** "Today: on 4h 10m · FIFA 26 1h 50m" from the agent's 'td' field. */
    static String today(org.json.JSONObject hb) {
        org.json.JSONObject td = hb.optJSONObject("td");
        if (td == null || td.optLong("on") <= 0) return "";
        StringBuilder b = new StringBuilder("Today: on ").append(duration(td.optLong("on")));
        org.json.JSONArray top = td.optJSONArray("top");
        if (top != null) {
            for (int i = 0; i < top.length(); i++) {
                org.json.JSONArray t = top.optJSONArray(i);
                if (t != null) b.append(" · ").append(t.optString(0)).append(" ").append(duration(t.optLong(1)));
            }
        }
        return b.toString();
    }

    /** "🎮 FIFA 26" for games/tracked apps, "🪟 Using Chrome" for background apps. */
    static String activity(org.json.JSONObject hb, boolean live) {
        if (!live) return "—";
        String app = hb.optString("app");
        if (!app.isEmpty()) {
            org.json.JSONArray na = hb.optJSONArray("na");
            boolean loud = na == null;                       // older agents: assume tracked
            if (na != null) for (int i = 0; i < na.length(); i++) if (app.equals(na.optString(i))) loud = true;
            return (loud ? "🎮 " : "🪟 Using ") + app;
        }
        return hb.optString("fg").isEmpty() ? "No tracked app open" : "In front: " + hb.optString("fg");
    }

    static String verdictIcon(String v) {
        if ("yes".equals(v)) return "✅ Yes";
        if ("maybe".equals(v)) return "⚠️ Maybe, test it";
        if ("no".equals(v)) return "❌ No";
        return "❔ Unknown";
    }

    /** Badge for the card: best of sleep/shutdown verdict, or a real test result. */
    static String wakeBadge(org.json.JSONObject wol, String tested) {
        if (tested != null) return tested.startsWith("ok") ? "⚡ Wake-up: ✅ tested, works"
                : "⚡ Wake-up: ❌ test failed";
        if (wol == null) return "";
        String s = wol.optString("sleep", "?");
        return "⚡ Wake from sleep: " + verdictIcon(s);
    }

    static String clock(long t) {
        return new java.text.SimpleDateFormat("HH:mm", java.util.Locale.getDefault())
                .format(new java.util.Date(t * 1000));
    }

    /** One history event as text, e.g. "⚽ Closed FIFA 26 · 1h 42m · 🌡 max 88°C". */
    static String event(org.json.JSONArray e) {
        String code = e.optString(1), arg = e.isNull(2) ? "" : e.optString(2, "");
        org.json.JSONObject x = e.optJSONObject(3);
        if (x == null) x = new org.json.JSONObject();
        switch (code) {
            case "on": return "🟢 Turned on" + ("start".equals(arg) ? " (DeviceWatch started)" : "");
            case "rs": return "🔁 DeviceWatch restarted";
            case "wk": return "☀️ Woke up" + ("network".equals(x.optString("by")) ? " (from your phone 📱)" : "");
            case "sl": return "😴 Went to sleep";
            case "off": return "🔴 Shut down";
            case "lost": return "⚠️ Disappeared (battery died, crash or forced off)";
            case "st": return "▶️ Opened " + arg;
            case "cl": {
                StringBuilder b = new StringBuilder("⏹ Closed ").append(arg);
                if (x.has("dur")) b.append(" · ").append(duration(x.optLong("dur")));
                if (x.has("cpu")) b.append(" · CPU ").append(x.optInt("cpu")).append("%");
                if (x.has("gpu")) b.append(" · GPU ").append(x.optInt("gpu")).append("%");
                if (x.has("ct") || x.has("gt")) {
                    b.append(" · 🌡 max ");
                    if (x.has("ct")) b.append(x.optInt("ct")).append("°C");
                    if (x.has("ct") && x.has("gt")) b.append(" / ");
                    if (x.has("gt")) b.append(x.optInt("gt")).append("°C");
                }
                return b.toString();
            }
            default: return code + " " + arg;
        }
    }

    /** A labelled horizontal bar: [label   ██████░░░░  1h 20m]. */
    static android.view.View bar(Context c, String label, long value, long max, int color) {
        LinearLayout row = row(c);
        row.setGravity(android.view.Gravity.CENTER_VERTICAL);
        row.setPadding(0, dp(c, 4), 0, dp(c, 4));
        TextView l = text(c, label, 13, TEXT, false);
        l.setSingleLine(true);
        l.setEllipsize(android.text.TextUtils.TruncateAt.END);
        row.addView(l, new LinearLayout.LayoutParams(dp(c, 110), -2));
        LinearLayout track = row(c);
        track.setBackground(round(c, 0xFF222632, 0, 6));
        View fill = new View(c);
        fill.setBackground(round(c, color, 0, 6));
        float w = max <= 0 ? 0 : Math.max(0.02f, Math.min(1f, value / (float) max));
        track.setWeightSum(1f);
        track.addView(fill, new LinearLayout.LayoutParams(0, dp(c, 10), w));
        LinearLayout.LayoutParams tl = new LinearLayout.LayoutParams(0, dp(c, 10), 1f);
        tl.setMargins(dp(c, 8), 0, dp(c, 8), 0);
        row.addView(track, tl);
        TextView v = text(c, duration(value), 12, DIM, false);
        v.setGravity(android.view.Gravity.END);
        row.addView(v, new LinearLayout.LayoutParams(dp(c, 64), -2));
        return row;
    }

    static TextView section(Context c, String title) {
        TextView t = text(c, title, 13, DIM, true);
        t.setAllCaps(true);
        t.setLetterSpacing(0.08f);
        t.setPadding(0, dp(c, 22), 0, dp(c, 8));
        return t;
    }

    static LinearLayout card(Context c) {
        LinearLayout card = column(c);
        int p = dp(c, 16);
        card.setPadding(p, p, p, p);
        card.setBackground(round(c, CARD, LINE, 18));
        return card;
    }

    static String ago(long sec) {
        if (sec < 60) return "just now";
        long m = sec / 60;
        if (m < 60) return m + " min ago";
        return (m / 60) + "h " + (m % 60) + "m ago";
    }
}
