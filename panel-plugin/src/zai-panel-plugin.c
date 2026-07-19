/*
 * xfce-zai-limits — native XFCE panel plugin for z.ai usage limits.
 *
 * A real panel widget (like cpugraph/systemload): graphical vertical bar,
 * set_tooltip_markup with the full weekly/5h/credits/age breakdown, 30s
 * refresh by spawning zai_limits.py --format json. No systray, no SNI,
 * no <tooltip>-tag-less genmon hacks.
 *
 * Build: see ../meson.build. The only runtime dep beyond what XFCE already
 * pulls in is json-glib (for parsing the script's JSON output).
 */

#include <libxfce4panel/libxfce4panel.h>
#include <gtk/gtk.h>
#include <json-glib/json-glib.h>

#ifndef ZAI_SCRIPT
#define ZAI_SCRIPT "/usr/bin/python3 /home/dp/MyProjects/xfce-zai-limits/zai_limits.py"
#endif

#define ZAI_INTERVAL_SEC 30
#define ZAI_WARN 70.0
#define ZAI_CRIT 90.0

typedef struct
{
    XfcePanelPlugin *plugin;
    GtkWidget       *da;
    gdouble          pct;            /* dominant used %, drives the bar */
    gdouble          primary_pct;    /* weekly, -1 if absent */
    gdouble          secondary_pct;  /* 5h,   -1 if absent */
    gint             primary_remain;
    gint             secondary_remain;
    gdouble          credits_balance;
    gboolean         credits_unlimited;
    gboolean         have_data;
    gint             age_sec;
} ZaiData;

/* forward */
static void     zai_construct (XfcePanelPlugin *plugin);
static gboolean zai_draw      (GtkWidget *w, cairo_t *cr, ZaiData *d);
static gboolean zai_refresh   (gpointer data);
static void     zai_parse     (ZaiData *d, const gchar *json);
static void     zai_update_tip(ZaiData *d);
static void     zai_about     (XfcePanelPlugin *plugin);

XFCE_PANEL_PLUGIN_REGISTER (zai_construct);

/* ----------------------------------------------------------------- */
static void
zai_construct (XfcePanelPlugin *plugin)
{
    ZaiData *d = g_new0 (ZaiData, 1);
    d->plugin = plugin;
    d->primary_pct = -1.0;
    d->secondary_pct = -1.0;

    d->da = gtk_drawing_area_new ();
    gtk_widget_set_size_request (d->da, 14, 14);
    gtk_widget_set_hexpand (d->da, TRUE);
    gtk_widget_set_vexpand (d->da, TRUE);
    g_signal_connect (G_OBJECT (d->da), "draw", G_CALLBACK (zai_draw), d);
    gtk_container_add (GTK_CONTAINER (plugin), d->da);
    gtk_widget_show (d->da);

    xfce_panel_plugin_add_action_widget (plugin, d->da);

    gtk_widget_set_tooltip_markup (GTK_WIDGET (plugin), "<b>z.ai</b> loading…");

    g_object_set_data_full (G_OBJECT (plugin), "zai-data", d, (GDestroyNotify) g_free);

    /* right-click → about; this also gives a native panel-item context menu */
    g_signal_connect (G_OBJECT (plugin), "about", G_CALLBACK (zai_about), NULL);

    g_timeout_add_seconds (ZAI_INTERVAL_SEC, zai_refresh, d);
    zai_refresh (d);
}

static void
zai_set_color (cairo_t *cr, gdouble pct)
{
    if (pct >= ZAI_CRIT)      cairo_set_source_rgb (cr, 0.878, 0.106, 0.141); /* red    */
    else if (pct >= ZAI_WARN) cairo_set_source_rgb (cr, 0.878, 0.608, 0.141); /* orange */
    else                      cairo_set_source_rgb (cr, 0.149, 0.635, 0.412); /* green  */
}

static gboolean
zai_draw (GtkWidget *w, cairo_t *cr, ZaiData *d)
{
    GtkAllocation alloc;
    gtk_widget_get_allocation (w, &alloc);
    gdouble W = alloc.width, H = alloc.height;
    if (W < 2.0 || H < 2.0)
        return FALSE;

    gdouble pad = 1.5;
    gdouble bw  = W - 2 * pad;
    gdouble bh  = H - 2 * pad;

    /* track */
    cairo_set_source_rgba (cr, 0.235, 0.235, 0.235, 1.0);
    cairo_rectangle (cr, pad, pad, bw, bh);
    cairo_fill ();

    /* fill: used % grows from the bottom */
    if (d->have_data && d->pct > 0.0) {
        gdouble fh = bh * (CLAMP (d->pct, 0.0, 100.0) / 100.0);
        zai_set_color (cr, d->pct);
        cairo_rectangle (cr, pad, pad + (bh - fh), bw, fh);
        cairo_fill ();
    }
    return FALSE;
}

/* ----------------------------------------------------------------- */
static gchar *
human_dur (gint sec)
{
    if (sec <= 0) return g_strdup ("now");
    gint dd = sec / 86400, r = sec % 86400;
    gint hh = r / 3600; r = r % 3600;
    gint mm = r / 60;
    if (dd > 0) return g_strdup_printf ("%dd %dh", dd, hh);
    if (hh > 0) return g_strdup_printf ("%dh %dm", hh, mm);
    return g_strdup_printf ("%dm", mm);
}

static gchar *
human_age (gint sec)
{
    if (sec < 60) return g_strdup_printf ("%ds ago", sec);
    gint m = sec / 60;
    if (m < 60) return g_strdup_printf ("%dm ago", m);
    gint h = m / 60, mm = m % 60;
    if (h < 48) return g_strdup_printf ("%dh %dm ago", h, mm);
    gint dd = h / 24, hh = h % 24;
    return g_strdup_printf ("%dd %dh ago", dd, hh);
}

static gchar *
pct_str (gdouble v)
{
    if (v < 0.0) return g_strdup ("  n/a");
    return g_strdup_printf ("%5.1f%%", v);
}

static void
zai_parse (ZaiData *d, const gchar *json)
{
    GError   *err  = NULL;
    JsonNode *root = json_from_string (json, &err);
    if (err) { g_error_free (err); d->have_data = FALSE; return; }
    if (!root || !JSON_NODE_HOLDS_OBJECT (root)) { d->have_data = FALSE; if (root) json_node_free (root); return; }

    JsonObject *obj = json_node_get_object (root);
    if (!json_object_get_boolean_member (obj, "ok")) {
        d->have_data = FALSE;
        json_node_free (root);
        return;
    }
    d->have_data = TRUE;
    d->age_sec   = (gint) json_object_get_int_member (obj, "age_sec");

    JsonObject *pr = json_object_get_object_member (obj, "primary");
    JsonObject *se = json_object_get_object_member (obj, "secondary");
    d->primary_pct = -1.0; d->primary_remain = 0;
    d->secondary_pct = -1.0; d->secondary_remain = 0;
    if (pr) {
        d->primary_pct    = json_object_get_double_member (pr, "used_percent");
        d->primary_remain = (gint) (json_object_has_member (pr, "resets_in_sec")
                                    ? json_object_get_int_member (pr, "resets_in_sec") : 0);
    }
    if (se) {
        d->secondary_pct    = json_object_get_double_member (se, "used_percent");
        d->secondary_remain = (gint) (json_object_has_member (se, "resets_in_sec")
                                      ? json_object_get_int_member (se, "resets_in_sec") : 0);
    }
    d->pct = d->primary_pct;
    if (d->secondary_pct > d->pct) d->pct = d->secondary_pct;
    if (d->pct < 0.0) d->pct = 0.0;

    JsonObject *cr = json_object_get_object_member (obj, "credits");
    d->credits_balance = 0.0; d->credits_unlimited = FALSE;
    if (cr) {
        d->credits_balance   = json_object_get_double_member (cr, "balance");
        d->credits_unlimited = json_object_get_boolean_member (cr, "unlimited");
    }
    json_node_free (root);
}

static void
zai_update_tip (ZaiData *d)
{
    gchar *pp = pct_str (d->primary_pct);
    gchar *pr = human_dur (d->primary_remain);
    gchar *sp = pct_str (d->secondary_pct);
    gchar *sr = human_dur (d->secondary_remain);
    gchar *ag = human_age (d->age_sec);
    gchar *cd = d->credits_unlimited
                    ? g_strdup ("unlimited")
                    : g_strdup_printf ("balance %g", d->credits_balance);

    gchar *tip = g_strdup_printf (
        "<tt><b>z.ai · %.0f%% used</b></tt>\n\n"
        "<tt>weekly</tt>  %s   <span foreground=\"#888\">resets in %s</span>\n"
        "<tt>5h</tt>      %s   <span foreground=\"#888\">resets in %s</span>\n\n"
        "<tt>credits</tt>  %s\n\n"
        "<span foreground=\"#888\" size=\"smaller\">updated %s</span>",
        d->pct, pp, pr, sp, sr, cd, ag);
    gtk_widget_set_tooltip_markup (GTK_WIDGET (d->plugin), tip);

    g_free (pp); g_free (pr); g_free (sp); g_free (sr); g_free (ag); g_free (cd); g_free (tip);
}

static gboolean
zai_refresh (gpointer data)
{
    ZaiData *d = (ZaiData *) data;
    gchar  *out = NULL, *serr = NULL;
    gint    est = 0;
    GError *err = NULL;
    gchar  *cmd = g_strdup_printf ("%s --format json", ZAI_SCRIPT);

    if (g_spawn_command_line_sync (cmd, &out, &serr, &est, &err) && est == 0 && out) {
        zai_parse (d, out);
        if (d->have_data)
            zai_update_tip (d);
        else
            gtk_widget_set_tooltip_markup (GTK_WIDGET (d->plugin), "<b>z.ai</b> no data\n(start a Codex session)");
    } else {
        if (err) {
            gchar *m = g_markup_escape_text (err->message, -1);
            gchar *t = g_strdup_printf ("<b>z.ai</b> error: %s", m);
            gtk_widget_set_tooltip_markup (GTK_WIDGET (d->plugin), t);
            g_free (m); g_free (t); g_error_free (err);
        }
    }
    g_free (cmd); g_free (out); g_free (serr);
    gtk_widget_queue_draw (d->da);
    return G_SOURCE_CONTINUE;
}

static void
zai_about (XfcePanelPlugin *plugin)
{
    static const gchar *authors[] = { "Dmitriy Prikotov", NULL };
    gtk_show_about_dialog (NULL,
        "program-name", "z.ai limits",
        "logo-icon-name", "org.xfce.genmon",
        "version", "0.1.0",
        "comments", "z.ai usage limits for the XFCE panel. "
                    "Reads Codex rollout logs — zero quota cost.",
        "authors", authors,
        "license", "MIT",
        "wrap-license", TRUE,
        NULL);
}
