<?php
/**
 * Storage: one row per page view in {prefix}sc_views. No cookies and no IP addresses are stored:
 * a visitor is a hash of IP + browser + site with a salt that changes every day, so the same
 * person cannot be recognised on another day and the hash cannot be turned back into an IP.
 * Rows older than KEEP_DAYS are deleted; the numbers themselves live in Stats Collector.
 */

defined('ABSPATH') || exit;

final class SC_Store
{
    public const DB_VERSION = '1';
    public const KEEP_DAYS = 35;
    public const DEDUPE_MINUTES = 30;

    public static function table(): string
    {
        global $wpdb;
        return $wpdb->prefix . 'sc_views';
    }

    public static function install(): void
    {
        global $wpdb;
        require_once ABSPATH . 'wp-admin/includes/upgrade.php';
        $table = self::table();
        $charset = $wpdb->get_charset_collate();
        dbDelta("CREATE TABLE {$table} (
            id bigint(20) unsigned NOT NULL AUTO_INCREMENT,
            token char(22) NOT NULL,
            ts datetime NOT NULL,
            hour datetime NOT NULL,
            day date NOT NULL,
            post_id bigint(20) unsigned NOT NULL DEFAULT 0,
            visitor char(16) NOT NULL,
            device varchar(8) NOT NULL DEFAULT 'desktop',
            referrer varchar(190) NOT NULL DEFAULT '',
            seconds int(10) unsigned NOT NULL DEFAULT 0,
            is_read tinyint(1) NOT NULL DEFAULT 0,
            shares smallint(5) unsigned NOT NULL DEFAULT 0,
            PRIMARY KEY  (id),
            UNIQUE KEY token (token),
            KEY hour (hour),
            KEY day (day),
            KEY dedupe (post_id, visitor, ts)
        ) {$charset};");
        update_option('sc_db_version', self::DB_VERSION, false);
    }

    public static function maybe_upgrade(): void
    {
        if (get_option('sc_db_version') !== self::DB_VERSION) {
            self::install();
        }
    }

    /** Salt for today (site time zone); a new random one every day. */
    public static function salt(): string
    {
        $today = wp_date('Y-m-d');
        $salt = get_option('sc_salt');
        if (!is_array($salt) || ($salt['day'] ?? '') !== $today) {
            $salt = ['day' => $today, 'salt' => bin2hex(random_bytes(16))];
            update_option('sc_salt', $salt, false);
        }
        return $salt['salt'];
    }

    public static function visitor_hash(string $ip, string $agent): string
    {
        return substr(hash('sha256', self::salt() . '|' . $ip . '|' . $agent . '|' . home_url()), 0, 16);
    }

    /** Records a view and returns its token; a reload within DEDUPE_MINUTES returns the earlier token. */
    public static function add_view(int $post_id, string $visitor, string $device, string $referrer): string
    {
        global $wpdb;
        $table = self::table();
        $now = time();
        $since = gmdate('Y-m-d H:i:s', $now - self::DEDUPE_MINUTES * 60);
        $existing = $wpdb->get_var($wpdb->prepare(
            "SELECT token FROM {$table} WHERE post_id = %d AND visitor = %s AND ts >= %s ORDER BY id DESC LIMIT 1",
            $post_id,
            $visitor,
            $since
        ));
        if ($existing) {
            return (string) $existing;
        }
        $token = rtrim(strtr(base64_encode(random_bytes(16)), '+/', '-_'), '=');
        $wpdb->insert($table, [
            'token' => $token,
            'ts' => gmdate('Y-m-d H:i:s', $now),
            'hour' => gmdate('Y-m-d H:00:00', $now),
            'day' => wp_date('Y-m-d', $now),
            'post_id' => $post_id,
            'visitor' => $visitor,
            'device' => $device,
            'referrer' => $referrer,
        ]);
        return $token;
    }

    /** Reading time and share clicks reported by the page while it is open. Values only go up. */
    public static function engage(string $token, int $seconds, bool $read, int $shares): void
    {
        global $wpdb;
        $table = self::table();
        $wpdb->query($wpdb->prepare(
            "UPDATE {$table} SET seconds = GREATEST(seconds, %d), is_read = GREATEST(is_read, %d),
             shares = GREATEST(shares, %d) WHERE token = %s AND ts >= %s",
            min(max($seconds, 0), 1800),
            $read ? 1 : 0,
            min(max($shares, 0), 50),
            $token,
            gmdate('Y-m-d H:i:s', time() - 6 * HOUR_IN_SECONDS)
        ));
    }

    public static function cleanup(): void
    {
        global $wpdb;
        $table = self::table();
        $wpdb->query($wpdb->prepare(
            "DELETE FROM {$table} WHERE ts < %s",
            gmdate('Y-m-d H:i:s', time() - self::KEEP_DAYS * DAY_IN_SECONDS)
        ));
    }
}
