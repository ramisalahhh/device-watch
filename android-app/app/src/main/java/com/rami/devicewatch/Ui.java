package com.rami.devicewatch;

import android.content.Context;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.util.TypedValue;
import android.view.Gravity;
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

    static String ago(long sec) {
        if (sec < 60) return "just now";
        long m = sec / 60;
        if (m < 60) return m + " min ago";
        return (m / 60) + "h " + (m % 60) + "m ago";
    }
}
