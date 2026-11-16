<?php
/**
 * Sends the numbers to Stats Collector every minute (WP-Cron). Each batch carries the full value of
 * every hour and day in it, so Stats Collector replaces what it had; a batch that fails is simply
 * sent again next minute. After a pause the plugin catches up 24 hours per batch.
 */

defined('ABSPATH') || exit;

final class SC_Sender
{
    private const CHUNK_HOURS = 24;
    private const VIDEO = '/<video|\[video|<iframe[^>]+(youtube|youtube-nocookie|vimeo|dailymotion)\.|youtube\.com\/(watch|embed|shorts)|youtu\.be\/|vimeo\.com\/\d|"providerNameSlug":"(youtube|vimeo|dailymotion)"/i';

    public static function init(): void
    {
        add_filter('cron_schedules', [self::class, 'schedules']);
        add_action('sc_push', [self::class, 'push']);
        add_action('sc_cleanup', ['SC_Store', 'cleanup']);
        if (!wp_next_scheduled('sc_push') || !wp_next_scheduled('sc_cleanup')) {
            self::schedule();
        }
    }

    public static function schedules(array $schedules): array
    {
        $schedules['sc_every_minute'] = ['interval' => 60, 'display' => __('Every minute', 'stats-collector')];
        return $schedules;
    }

    public static function schedule(): void
    {
        add_filter('cron_schedules', [self::class, 'schedules']);
        if (!wp_next_scheduled('sc_push')) {
            wp_schedule_event(time() + 60, 'sc_every_minute', 'sc_push');
        }
        if (!wp_next_scheduled('sc_cleanup')) {
            wp_schedule_event(time() + HOUR_IN_SECONDS, 'daily', 'sc_cleanup');
        }
    }

    public static function unschedule(): void
    {
        wp_clear_scheduled_hook('sc_push');
        wp_clear_scheduled_hook('sc_cleanup');
    }

    private static function status(array $changes = []): array
    {
        $status = get_option('sc_status');
        $status = is_array($status) ? $status : [];
        if ($changes) {
            $status = array_merge($status, $changes);
            update_option('sc_status', $status, false);
        }
        return $status;
    }

    /** @return array{0: bool, 1: string, 2: array|null} */
    public static function send(array $payload): array
    {
        $url = SC_Admin::base_url((string) SC_Admin::setting('url')) . '/api/ingest/wordpress';
        $body = wp_json_encode($payload);
        $ts = (string) time();
        $signature = 'sha256=' . hash_hmac('sha256', $ts . '.' . $body, (string) SC_Admin::setting('secret'));
        $response = wp_remote_post($url, [
            'timeout' => 20,
            'headers' => [
                'Content-Type' => 'application/json',
                'X-SC-Key' => (string) SC_Admin::setting('key'),
                'X-SC-Timestamp' => $ts,
                'X-SC-Signature' => $signature,
                'User-Agent' => 'StatsCollectorWP/' . SC_VERSION,
            ],
            'body' => $body,
        ]);
        if (is_wp_error($response)) {
            return [false, $response->get_error_message(), null];
        }
        $code = wp_remote_retrieve_response_code($response);
        if ($code === 404 || $code === 405) {
            return [false, sprintf(
                /* translators: %d: HTTP status code */
                __('HTTP %d: check the Stats Collector address. Enter only the address with https://, for example https://stats.example.org.', 'stats-collector'),
                $code
            ), null];
        }
        $data = json_decode(wp_remote_retrieve_body($response), true);
        if ($code !== 200 || !is_array($data) || empty($data['ok'])) {
            $error = is_array($data) && !empty($data['error']) ? (string) $data['error'] : 'HTTP ' . $code;
            return [false, $error, is_array($data) ? $data : null];
        }
        return [true, '', $data];
    }

    private static function site(): array
    {
        return [
            'url' => home_url(),
            'name' => get_bloginfo('name'),
            'timezone' => wp_timezone_string(),
            'plugin' => SC_VERSION,
            'wp' => get_bloginfo('version'),
        ];
    }

    public static function ping(): array
    {
        [$ok, $error, $data] = self::send(['v' => 1, 'ping' => true, 'site' => self::site()]);
        return [$ok, $ok ? (string) ($data['source'] ?? '') : $error];
    }

    public static function push(): void
    {
        if (!SC_Admin::configured()) {
            return;
        }
        if (get_transient('sc_push_lock')) {
            return;
        }
        set_transient('sc_push_lock', 1, 55);
        try {
            self::push_once();
        } finally {
            delete_transient('sc_push_lock');
        }
    }

    public static function push_once(): void
    {
        global $wpdb;
        $table = SC_Store::table();
        $now_hour = (int) (floor(time() / HOUR_IN_SECONDS) * HOUR_IN_SECONDS);
        $status = self::status();
        $cursor = isset($status['cursor']) ? (int) $status['cursor'] : null;
        if ($cursor === null) {
            $first = $wpdb->get_var("SELECT MIN(hour) FROM {$table}");
            $cursor = $first ? strtotime($first . ' UTC') : $now_hour;
        }
        $from = min($cursor, $now_hour - HOUR_IN_SECONDS);
        $from = max($from, $now_hour - SC_Store::KEEP_DAYS * DAY_IN_SECONDS);
        $to = min($from + self::CHUNK_HOURS * HOUR_IN_SECONDS, $now_hour + HOUR_IN_SECONDS);
        $payload = self::build($from, $to);
        [$ok, $error, $data] = self::send($payload);
        if ($ok) {
            // Caught up: next time start at the previous hour again (late reading time still comes in).
            $next = $to > $now_hour ? $now_hour - HOUR_IN_SECONDS : $to;
            self::status([
                'cursor' => $next,
                'last_ok' => time(),
                'last_error' => '',
                'last_result' => array_intersect_key($data ?? [], array_flip(['items', 'hours', 'days'])),
            ]);
        } else {
            self::status(['last_error' => $error, 'last_error_at' => time()]);
        }
    }

    /** Numbers for the hours [from, to) and the site days they touch. */
    public static function build(int $from, int $to): array
    {
        global $wpdb;
        $table = SC_Store::table();
        $f = gmdate('Y-m-d H:i:s', $from);
        $t = gmdate('Y-m-d H:i:s', $to);
        $hours = [];
        $key = static fn ($hour, $post) => $hour . '|' . $post;
        $add = static function (array &$rows, string $hour, int $post, array $values) use ($key) {
            $k = $key($hour, $post);
            if (!isset($rows[$k])) {
                $rows[$k] = ['hour' => gmdate('c', strtotime($hour . ' UTC')), 'post' => $post];
            }
            foreach ($values as $name => $value) {
                $rows[$k][$name] = ($rows[$k][$name] ?? 0) + (int) $value;
            }
        };
        $per_post = $wpdb->get_results($wpdb->prepare(
            "SELECT hour, post_id, COUNT(*) views, COUNT(DISTINCT visitor) visitors, SUM(seconds) read_seconds,
             SUM(is_read) `reads`, SUM(shares) shares FROM {$table}
             WHERE hour >= %s AND hour < %s AND post_id > 0 GROUP BY hour, post_id",
            $f,
            $t
        ), ARRAY_A);
        foreach ($per_post as $r) {
            $add($hours, $r['hour'], (int) $r['post_id'], array_intersect_key($r, array_flip(['views', 'visitors', 'read_seconds', 'reads', 'shares'])));
        }
        $site = $wpdb->get_results($wpdb->prepare(
            "SELECT hour, COUNT(*) views, COUNT(DISTINCT visitor) visitors, SUM(seconds) read_seconds,
             SUM(is_read) `reads`, SUM(shares) shares FROM {$table} WHERE hour >= %s AND hour < %s GROUP BY hour",
            $f,
            $t
        ), ARRAY_A);
        foreach ($site as $r) {
            $add($hours, $r['hour'], 0, array_intersect_key($r, array_flip(['views', 'visitors', 'read_seconds', 'reads', 'shares'])));
        }
        $comments = $wpdb->get_results($wpdb->prepare(
            "SELECT DATE_FORMAT(comment_date_gmt, '%%Y-%%m-%%d %%H:00:00') hour, comment_post_ID post_id, COUNT(*) n
             FROM {$wpdb->comments} WHERE comment_approved = '1' AND comment_type IN ('comment', '')
             AND comment_date_gmt >= %s AND comment_date_gmt < %s GROUP BY hour, post_id",
            $f,
            $t
        ), ARRAY_A);
        foreach ($comments as $r) {
            $add($hours, $r['hour'], (int) $r['post_id'], ['comments' => $r['n']]);
            $add($hours, $r['hour'], 0, ['comments' => $r['n']]);
        }

        // Days in the site time zone that these hours touch (plus today).
        $first_day = wp_date('Y-m-d', $from);
        $last_day = wp_date('Y-m-d', min($to - 1, time()));
        $days = [];
        $dk = static fn ($day, $post) => $day . '|' . $post;
        $visitor_days = $wpdb->get_results($wpdb->prepare(
            "SELECT day, post_id, COUNT(DISTINCT visitor) visitors FROM {$table}
             WHERE day >= %s AND day <= %s GROUP BY day, post_id",
            $first_day,
            $last_day
        ), ARRAY_A);
        foreach ($visitor_days as $r) {
            if ((int) $r['post_id'] > 0) {
                $days[$dk($r['day'], (int) $r['post_id'])] = ['day' => $r['day'], 'post' => (int) $r['post_id'], 'visitors' => (int) $r['visitors']] + self::EMPTY_DAY;
            }
        }
        $site_days = $wpdb->get_results($wpdb->prepare(
            "SELECT day, COUNT(DISTINCT visitor) visitors FROM {$table} WHERE day >= %s AND day <= %s GROUP BY day",
            $first_day,
            $last_day
        ), ARRAY_A);
        foreach ($site_days as $r) {
            $days[$dk($r['day'], 0)] = ['day' => $r['day'], 'post' => 0, 'visitors' => (int) $r['visitors']] + self::EMPTY_DAY;
        }
        // Site searches per day: every term, and the terms that found nothing.
        $searches = SC_Store::search_table();
        $terms = $wpdb->get_results($wpdb->prepare(
            "SELECT day, term, COUNT(*) n, SUM(results = 0) none_found FROM {$searches} WHERE day >= %s AND day <= %s
             GROUP BY day, term ORDER BY n DESC LIMIT 2000",
            $first_day,
            $last_day
        ), ARRAY_A);
        foreach ($terms as $r) {
            $k = $dk($r['day'], 0);
            if (!isset($days[$k])) {
                $days[$k] = ['day' => $r['day'], 'post' => 0, 'visitors' => 0] + self::EMPTY_DAY;
            }
            $days[$k]['searches'][$r['term']] = (int) $r['n'];
            if ((int) $r['none_found'] > 0) {
                $days[$k]['searches_empty'][$r['term']] = (int) $r['none_found'];
            }
        }
        // Scroll depth in steps of 25% (only views that reported back), and UTM campaigns.
        $columns = [
            'referrers' => ['referrer', ''],
            'devices' => ['device', ''],
            'scroll' => ['FLOOR(LEAST(scroll, 100) / 25) * 25', 'AND scroll > 0'],
            'campaigns' => ['campaign', "AND campaign <> ''"],
        ];
        foreach ($columns as $field => [$column, $filter]) {
            $rows = $wpdb->get_results($wpdb->prepare(
                "SELECT day, post_id, {$column} k, COUNT(*) n FROM {$table} WHERE day >= %s AND day <= %s {$filter} GROUP BY day, post_id, k",
                $first_day,
                $last_day
            ), ARRAY_A);
            foreach ($rows as $r) {
                $name = (string) $r['k'] !== '' ? (string) $r['k'] : 'direct';
                foreach (array_unique([(int) $r['post_id'], 0]) as $post) {
                    $k = $dk($r['day'], $post);
                    if (isset($days[$k])) {
                        $days[$k][$field][$name] = ($days[$k][$field][$name] ?? 0) + (int) $r['n'];
                    }
                }
            }
        }
        foreach ($days as &$d) {
            foreach (array_keys(self::EMPTY_DAY) as $field) {
                arsort($d[$field]);
                $d[$field] = (object) array_slice($d[$field], 0, $field === 'searches' || $field === 'searches_empty' ? 200 : 50, true);
            }
            if ($d['post'] !== 0) {
                unset($d['searches'], $d['searches_empty']);
            }
        }
        unset($d);

        // Articles published in these hours are sent even before anyone read them (production per editor).
        $published = array_map('intval', $wpdb->get_col($wpdb->prepare(
            "SELECT ID FROM {$wpdb->posts} WHERE post_status = 'publish' AND post_date_gmt >= %s AND post_date_gmt < %s
             AND post_type IN (" . implode(',', array_fill(0, count(self::types()), '%s')) . ') LIMIT 500',
            $f,
            $t,
            ...self::types()
        )));
        $post_ids = array_unique(array_merge(
            array_filter(array_map(static fn ($r) => $r['post'], array_merge(array_values($hours), array_values($days)))),
            $published
        ));
        [$items, $authors] = self::items($post_ids);
        [$production, $authors] = self::production($authors);
        return [
            'v' => 1,
            'site' => self::site(),
            'authors' => array_values($authors),
            'items' => $items,
            'hours' => array_values($hours),
            'days' => array_values($days),
            'live' => self::live(),
            'production' => $production,
        ];
    }

    private const EMPTY_DAY = ['referrers' => [], 'devices' => [], 'scroll' => [], 'campaigns' => [], 'searches' => [], 'searches_empty' => []];

    /** @return string[] */
    private static function types(): array
    {
        $types = (array) SC_Admin::setting('post_types');
        return $types ?: ['post'];
    }

    /** Readers now: views that were open (and reported back) in the last five minutes, per article. */
    public static function live(): array
    {
        global $wpdb;
        $table = SC_Store::table();
        $since = gmdate('Y-m-d H:i:s', time() - 5 * MINUTE_IN_SECONDS);
        $readers = (int) $wpdb->get_var($wpdb->prepare("SELECT COUNT(DISTINCT visitor) FROM {$table} WHERE seen >= %s", $since));
        $rows = $wpdb->get_results($wpdb->prepare(
            "SELECT post_id, COUNT(DISTINCT visitor) n FROM {$table} WHERE seen >= %s AND post_id > 0
             GROUP BY post_id ORDER BY n DESC LIMIT 20",
            $since
        ), ARRAY_A);
        $posts = [];
        foreach ($rows as $r) {
            $posts[(string) $r['post_id']] = (int) $r['n'];
        }
        return ['at' => gmdate('c'), 'readers' => $readers, 'posts' => (object) $posts];
    }

    /** What the newsroom has in the pipeline: scheduled articles, drafts, pending review and comments. */
    private static function production(array $authors): array
    {
        global $wpdb;
        $counts = ['scheduled' => 0, 'drafts' => 0, 'pending' => 0];
        foreach (self::types() as $type) {
            $c = wp_count_posts($type);
            $counts['scheduled'] += (int) ($c->future ?? 0);
            $counts['drafts'] += (int) ($c->draft ?? 0);
            $counts['pending'] += (int) ($c->pending ?? 0);
        }
        $comments = wp_count_comments();
        $counts['pending_comments'] = (int) ($comments->moderated ?? 0);
        $scheduled = [];
        $send_email = (bool) SC_Admin::setting('send_emails');
        foreach (get_posts(['post_type' => self::types(), 'post_status' => 'future', 'orderby' => 'date', 'order' => 'ASC', 'numberposts' => 20]) as $post) {
            $uid = (int) $post->post_author;
            if ($uid && !isset($authors[$uid]) && ($user = get_userdata($uid))) {
                $authors[$uid] = ['id' => $uid, 'name' => $user->display_name] + ($send_email ? ['email' => $user->user_email] : []);
            }
            $scheduled[] = [
                'id' => $post->ID,
                'title' => html_entity_decode(get_the_title($post), ENT_QUOTES, 'UTF-8'),
                'at' => gmdate('c', strtotime($post->post_date_gmt . ' UTC')),
                'author' => $uid,
            ];
        }
        return [$counts + ['scheduled_items' => $scheduled], $authors];
    }

    /** Number of words in the text of a post, without HTML and shortcodes. */
    private static function words(string $content): int
    {
        $text = trim(wp_strip_all_tags(strip_shortcodes($content)));
        return $text === '' ? 0 : count(preg_split('/\s+/u', $text) ?: []);
    }

    /** Focus keyword and scores from Yoast SEO or Rank Math, when one of them is used. */
    private static function seo(int $post_id): ?array
    {
        $yoast = get_post_meta($post_id, '_yoast_wpseo_focuskw', true);
        $yoast_score = get_post_meta($post_id, '_yoast_wpseo_linkdex', true);
        if ($yoast !== '' || $yoast_score !== '') {
            $readability = get_post_meta($post_id, '_yoast_wpseo_content_score', true);
            return [
                'plugin' => 'yoast',
                'keyword' => mb_substr((string) $yoast, 0, 100),
                'score' => $yoast_score !== '' ? (int) $yoast_score : null,
                'readability' => $readability !== '' ? (int) $readability : null,
            ];
        }
        $rank = get_post_meta($post_id, 'rank_math_focus_keyword', true);
        $rank_score = get_post_meta($post_id, 'rank_math_seo_score', true);
        if ($rank !== '' || $rank_score !== '') {
            return [
                'plugin' => 'rankmath',
                'keyword' => mb_substr(trim(explode(',', (string) $rank)[0]), 0, 100),
                'score' => $rank_score !== '' ? (int) $rank_score : null,
                'readability' => null,
            ];
        }
        return null;
    }

    /** Article details and their authors (Co-Authors Plus is used when it is installed). */
    private static function items(array $post_ids): array
    {
        global $wpdb;
        $items = [];
        $authors = [];
        // Revisions per post, and how many of them were made more than 15 minutes after publication (updates).
        $revisions = [];
        $ids = array_values(array_filter(array_map('intval', $post_ids)));
        if ($ids) {
            $rows = $wpdb->get_results(
                "SELECT r.post_parent id, COUNT(*) n, SUM(r.post_date_gmt > DATE_ADD(p.post_date_gmt, INTERVAL 15 MINUTE)) updates
                 FROM {$wpdb->posts} r JOIN {$wpdb->posts} p ON p.ID = r.post_parent
                 WHERE r.post_type = 'revision' AND r.post_parent IN (" . implode(',', $ids) . ') GROUP BY r.post_parent',
                ARRAY_A
            );
            foreach ($rows as $r) {
                $revisions[(int) $r['id']] = [(int) $r['n'], (int) $r['updates']];
            }
        }
        $send_email = (bool) SC_Admin::setting('send_emails');
        foreach ($post_ids as $id) {
            $post = get_post((int) $id);
            if (!$post) {
                continue;
            }
            $user_ids = [(int) $post->post_author];
            if (function_exists('get_coauthors')) {
                $co = array_map(static fn ($a) => (int) ($a->ID ?? 0), (array) get_coauthors($post->ID));
                $user_ids = array_values(array_filter($co)) ?: $user_ids;
            }
            foreach ($user_ids as $uid) {
                if ($uid && !isset($authors[$uid]) && ($user = get_userdata($uid))) {
                    $authors[$uid] = ['id' => $uid, 'name' => $user->display_name] + ($send_email ? ['email' => $user->user_email] : []);
                }
            }
            $terms = static fn ($taxonomy) => array_values(array_map(
                static fn ($term) => html_entity_decode($term->name, ENT_QUOTES, 'UTF-8'),
                wp_get_post_terms($post->ID, $taxonomy) ?: []
            ));
            $items[] = [
                'id' => $post->ID,
                'type' => $post->post_type,
                'title' => html_entity_decode(get_the_title($post), ENT_QUOTES, 'UTF-8'),
                'url' => get_permalink($post),
                'published_at' => $post->post_date_gmt && $post->post_date_gmt !== '0000-00-00 00:00:00' ? gmdate('c', strtotime($post->post_date_gmt . ' UTC')) : null,
                'authors' => $user_ids,
                'categories' => is_object_in_taxonomy($post->post_type, 'category') ? $terms('category') : [],
                'tags' => is_object_in_taxonomy($post->post_type, 'post_tag') ? $terms('post_tag') : [],
                'comments' => (int) $post->comment_count,
                'modified_at' => $post->post_modified_gmt && $post->post_modified_gmt !== '0000-00-00 00:00:00' ? gmdate('c', strtotime($post->post_modified_gmt . ' UTC')) : null,
                'words' => self::words((string) $post->post_content),
                'images' => substr_count(strtolower((string) $post->post_content), '<img'),
                'featured_image' => has_post_thumbnail($post),
                'video' => (bool) preg_match(self::VIDEO, (string) $post->post_content),
                'revisions' => $revisions[$post->ID][0] ?? 0,
                'updates' => $revisions[$post->ID][1] ?? 0,
                'seo' => self::seo($post->ID),
            ];
        }
        return [$items, $authors];
    }
}
