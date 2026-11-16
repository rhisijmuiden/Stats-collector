<?php
/**
 * Counting on the website: a small script (assets/tracker.js) reports a view (with its UTM campaign)
 * and, while the page is open, the visible reading time, scroll depth, whether the article was read
 * and share-button clicks. On the search results page it reports the search term instead.
 */

defined('ABSPATH') || exit;

final class SC_Tracker
{
    private const BOTS = '/bot|crawl|spider|slurp|facebookexternalhit|embedly|preview|headless|lighthouse|pingdom|uptime|monitor|curl|wget|python|java\/|go-http|okhttp|feedfetcher|mediapartners/i';

    public static function init(): void
    {
        add_action('rest_api_init', [self::class, 'routes']);
        add_action('wp_enqueue_scripts', [self::class, 'enqueue']);
    }

    public static function routes(): void
    {
        register_rest_route('stats-collector/v1', '/view', [
            'methods' => 'POST',
            'callback' => [self::class, 'view'],
            'permission_callback' => '__return_true',
        ]);
        register_rest_route('stats-collector/v1', '/search', [
            'methods' => 'POST',
            'callback' => [self::class, 'search'],
            'permission_callback' => '__return_true',
        ]);
        register_rest_route('stats-collector/v1', '/engage', [
            'methods' => 'POST',
            'callback' => [self::class, 'engage'],
            'permission_callback' => '__return_true',
        ]);
    }

    /** Post id to count for the current page: the post or page itself, 0 for the home page. */
    private static function current_post_id(): ?int
    {
        $types = SC_Admin::setting('post_types');
        if (is_singular($types)) {
            return (int) get_queried_object_id();
        }
        if (is_front_page() || is_home()) {
            return 0;
        }
        return null;
    }

    public static function enqueue(): void
    {
        if (!SC_Admin::configured() || self::excluded_user()) {
            return;
        }
        $config = [];
        if (is_search() && SC_Admin::setting('count_searches')) {
            global $wp_query;
            $term = self::clean_term((string) get_search_query(false));
            if ($term === '' || is_paged()) {
                return;
            }
            $config = [
                'search' => $term,
                'results' => (int) ($wp_query->found_posts ?? 0),
                'searchUrl' => esc_url_raw(rest_url('stats-collector/v1/search')),
            ];
        } else {
            $post_id = self::current_post_id();
            if ($post_id === null) {
                return;
            }
            $config = [
                'post' => $post_id,
                'view' => esc_url_raw(rest_url('stats-collector/v1/view')),
                'engage' => esc_url_raw(rest_url('stats-collector/v1/engage')),
            ];
        }
        wp_enqueue_script('stats-collector', plugins_url('assets/tracker.js', SC_FILE), [], SC_VERSION, [
            'in_footer' => true,
            'strategy' => 'defer',
        ]);
        wp_add_inline_script('stats-collector', 'window.scConfig = ' . wp_json_encode($config) . ';', 'before');
    }

    private static function excluded_user(): bool
    {
        return SC_Admin::setting('exclude_editors') && is_user_logged_in() && current_user_can('edit_posts');
    }

    private static function client_ip(): string
    {
        $header = SC_Admin::setting('ip_header');
        if ($header) {
            $key = 'HTTP_' . strtoupper(str_replace('-', '_', $header));
            if (!empty($_SERVER[$key])) {
                return trim(explode(',', (string) $_SERVER[$key])[0]);
            }
        }
        return (string) ($_SERVER['REMOTE_ADDR'] ?? '');
    }

    public static function device(string $agent): string
    {
        if (preg_match('/iPad|Tablet|PlayBook|Silk|(Android(?!.*Mobile))/i', $agent)) {
            return 'tablet';
        }
        if (preg_match('/Mobi|iPhone|iPod|Android|BlackBerry|Opera Mini|IEMobile/i', $agent)) {
            return 'mobile';
        }
        return 'desktop';
    }

    /** Domain of the referring site, without www; empty for direct visits and the site itself. */
    public static function referrer_domain(string $referrer): string
    {
        $host = strtolower((string) wp_parse_url($referrer, PHP_URL_HOST));
        $host = preg_replace('/^(www|m|l|lm)\./', '', $host);
        $own = preg_replace('/^www\./', '', strtolower((string) wp_parse_url(home_url(), PHP_URL_HOST)));
        if (!$host || $host === $own || !preg_match('/^[a-z0-9.\-]{1,190}$/', $host)) {
            return '';
        }
        return $host;
    }

    /** A search term as it is counted: lower case, single spaces, at most 100 characters. */
    public static function clean_term(string $term): string
    {
        $term = wp_strip_all_tags($term);
        $term = preg_replace('/\s+/u', ' ', $term);
        return mb_substr(mb_strtolower(trim((string) $term)), 0, 100);
    }

    /** "source|medium|campaign" from the utm_ parameters of the page address, or empty. */
    public static function campaign(array $utm): string
    {
        $parts = [];
        foreach (['source', 'medium', 'campaign'] as $key) {
            $value = mb_strtolower(trim((string) ($utm[$key] ?? '')));
            $value = preg_replace('/[^\p{L}\p{N} ._+\-]/u', '', $value);
            $parts[] = mb_substr((string) $value, 0, 60);
        }
        return $parts[0] === '' && $parts[2] === '' ? '' : implode('|', $parts);
    }

    private static function is_bot(WP_REST_Request $request, string $agent): bool
    {
        $purpose = (string) ($request->get_header('sec_purpose') ?: $request->get_header('purpose'));
        return $agent === '' || preg_match(self::BOTS, $agent) || stripos($purpose, 'prefetch') !== false || self::excluded_user();
    }

    public static function search(WP_REST_Request $request): WP_REST_Response
    {
        $agent = substr((string) $request->get_header('user_agent'), 0, 400);
        if (!SC_Admin::setting('count_searches') || self::is_bot($request, $agent)) {
            return new WP_REST_Response(null, 204);
        }
        $term = self::clean_term((string) $request->get_param('q'));
        if ($term === '') {
            return new WP_REST_Response(null, 204);
        }
        // The number of results is looked up again here, so a visitor cannot make a term look empty.
        $found = new WP_Query(['s' => $term, 'post_status' => 'publish', 'posts_per_page' => 1, 'fields' => 'ids', 'no_found_rows' => false]);
        SC_Store::add_search(SC_Store::visitor_hash(self::client_ip(), $agent), $term, (int) $found->found_posts);
        return new WP_REST_Response(null, 204);
    }

    public static function view(WP_REST_Request $request): WP_REST_Response
    {
        $agent = substr((string) $request->get_header('user_agent'), 0, 400);
        if (self::is_bot($request, $agent)) {
            return new WP_REST_Response(['t' => null], 200);
        }
        $post_id = (int) $request->get_param('post');
        if ($post_id > 0) {
            $post = get_post($post_id);
            if (!$post || $post->post_status !== 'publish' || !in_array($post->post_type, SC_Admin::setting('post_types'), true)) {
                return new WP_REST_Response(['t' => null], 200);
            }
        } elseif ($post_id < 0) {
            return new WP_REST_Response(['t' => null], 200);
        }
        $visitor = SC_Store::visitor_hash(self::client_ip(), $agent);
        $token = SC_Store::add_view(
            $post_id,
            $visitor,
            self::device($agent),
            self::referrer_domain((string) $request->get_param('ref')),
            self::campaign(is_array($request->get_param('utm')) ? $request->get_param('utm') : [])
        );
        $response = new WP_REST_Response(['t' => $token], 200);
        $response->header('Cache-Control', 'no-store');
        return $response;
    }

    public static function engage(WP_REST_Request $request): WP_REST_Response
    {
        // sendBeacon posts text/plain, so read the raw body as JSON.
        $data = json_decode((string) $request->get_body(), true);
        if (!is_array($data) || empty($data['t']) || !is_string($data['t']) || !preg_match('/^[A-Za-z0-9_-]{22}$/', $data['t'])) {
            return new WP_REST_Response(null, 204);
        }
        SC_Store::engage($data['t'], (int) ($data['s'] ?? 0), !empty($data['r']), (int) ($data['sh'] ?? 0), (int) ($data['sc'] ?? 0));
        return new WP_REST_Response(null, 204);
    }
}
