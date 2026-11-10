<?php
/** Settings → Stats Collector: connection, what is counted, and the status of the last batch. */

defined('ABSPATH') || exit;

final class SC_Admin
{
    private const DEFAULTS = [
        'url' => '',
        'key' => '',
        'secret' => '',
        'post_types' => ['post', 'page'],
        'exclude_editors' => true,
        'ip_header' => '',
        'send_emails' => true,
    ];
    private const IP_HEADERS = ['', 'CF-Connecting-IP', 'X-Forwarded-For', 'X-Real-IP'];

    public static function init(): void
    {
        add_action('admin_menu', [self::class, 'menu']);
        add_action('admin_post_sc_save', [self::class, 'save']);
        add_action('admin_post_sc_test', [self::class, 'test']);
        add_action('admin_post_sc_push', [self::class, 'push_now']);
        add_filter('plugin_action_links_' . plugin_basename(SC_FILE), [self::class, 'links']);
    }

    public static function settings(): array
    {
        $saved = get_option('sc_settings');
        return array_merge(self::DEFAULTS, is_array($saved) ? $saved : []);
    }

    public static function setting(string $name)
    {
        return self::settings()[$name] ?? null;
    }

    public static function configured(): bool
    {
        $s = self::settings();
        return $s['url'] !== '' && $s['key'] !== '' && $s['secret'] !== '';
    }

    public static function links(array $links): array
    {
        array_unshift($links, '<a href="' . esc_url(admin_url('options-general.php?page=stats-collector')) . '">' . esc_html__('Settings', 'stats-collector') . '</a>');
        return $links;
    }

    public static function menu(): void
    {
        add_options_page('Stats Collector', 'Stats Collector', 'manage_options', 'stats-collector', [self::class, 'page']);
    }

    private static function back(string $notice, string $type = 'success'): void
    {
        set_transient('sc_notice_' . get_current_user_id(), ['text' => $notice, 'type' => $type], 60);
        wp_safe_redirect(admin_url('options-general.php?page=stats-collector'));
        exit;
    }

    public static function save(): void
    {
        if (!current_user_can('manage_options')) {
            wp_die(esc_html__('You are not allowed to do this.', 'stats-collector'), 403);
        }
        check_admin_referer('sc_save');
        $s = self::settings();
        $url = esc_url_raw(trim(wp_unslash($_POST['url'] ?? '')));
        $s['url'] = preg_match('#^https?://#', $url) ? rtrim($url, '/') : '';
        $s['key'] = sanitize_text_field(wp_unslash($_POST['key'] ?? ''));
        $secret = trim((string) wp_unslash($_POST['secret'] ?? ''));
        if ($secret !== '') {
            $s['secret'] = $secret;
        }
        $types = array_map('sanitize_key', (array) wp_unslash($_POST['post_types'] ?? []));
        $s['post_types'] = array_values(array_intersect($types, get_post_types(['public' => true])));
        $s['exclude_editors'] = !empty($_POST['exclude_editors']);
        $s['send_emails'] = !empty($_POST['send_emails']);
        $header = (string) wp_unslash($_POST['ip_header'] ?? '');
        $s['ip_header'] = in_array($header, self::IP_HEADERS, true) ? $header : '';
        update_option('sc_settings', $s, false);
        self::back(__('Settings saved.', 'stats-collector'));
    }

    public static function test(): void
    {
        if (!current_user_can('manage_options')) {
            wp_die(esc_html__('You are not allowed to do this.', 'stats-collector'), 403);
        }
        check_admin_referer('sc_test');
        if (!self::configured()) {
            self::back(__('Fill in the address, site key and secret first.', 'stats-collector'), 'error');
        }
        [$ok, $message] = SC_Sender::ping();
        if ($ok) {
            /* translators: %s: name of the source in Stats Collector */
            self::back(sprintf(__('Connection works. Stats Collector knows this site as "%s".', 'stats-collector'), $message));
        }
        self::back(sprintf(__('Connection failed: %s', 'stats-collector'), self::explain($message)), 'error');
    }

    public static function push_now(): void
    {
        if (!current_user_can('manage_options')) {
            wp_die(esc_html__('You are not allowed to do this.', 'stats-collector'), 403);
        }
        check_admin_referer('sc_push');
        SC_Sender::push();
        $status = get_option('sc_status');
        if (!empty($status['last_error']) && ($status['last_error_at'] ?? 0) >= time() - 5) {
            self::back(sprintf(__('Sending failed: %s', 'stats-collector'), self::explain((string) $status['last_error'])), 'error');
        }
        self::back(__('Numbers sent.', 'stats-collector'));
    }

    private static function explain(string $code): string
    {
        $map = [
            'bad_signature' => __('the site key or secret is wrong.', 'stats-collector'),
            'missing_signature' => __('the site key or secret is missing.', 'stats-collector'),
            'clock_skew' => __('the clock of this server is more than five minutes off.', 'stats-collector'),
            'source_disabled' => __('this site is paused in Stats Collector.', 'stats-collector'),
            'too_large' => __('the batch is too large.', 'stats-collector'),
        ];
        return $map[$code] ?? $code;
    }

    public static function page(): void
    {
        if (!current_user_can('manage_options')) {
            return;
        }
        $s = self::settings();
        $status = get_option('sc_status');
        $status = is_array($status) ? $status : [];
        $notice = get_transient('sc_notice_' . get_current_user_id());
        delete_transient('sc_notice_' . get_current_user_id());
        $types = get_post_types(['public' => true], 'objects');
        unset($types['attachment']);
        $fmt = static fn ($ts) => $ts ? wp_date(get_option('date_format') . ' ' . get_option('time_format'), (int) $ts) : '–';
        ?>
        <div class="wrap">
            <h1>Stats Collector</h1>
            <?php if ($notice) : ?>
                <div class="notice notice-<?php echo esc_attr($notice['type']); ?> is-dismissible"><p><?php echo esc_html($notice['text']); ?></p></div>
            <?php endif; ?>
            <p><?php esc_html_e('Counts page views, visitors, reading time and share clicks per article without cookies, and sends them every minute to Stats Collector.', 'stats-collector'); ?></p>

            <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>">
                <input type="hidden" name="action" value="sc_save">
                <?php wp_nonce_field('sc_save'); ?>
                <h2><?php esc_html_e('Connection', 'stats-collector'); ?></h2>
                <p class="description"><?php esc_html_e('Copy these values from Stats Collector: Sources → your website.', 'stats-collector'); ?></p>
                <table class="form-table" role="presentation">
                    <tr><th scope="row"><label for="sc-url"><?php esc_html_e('Stats Collector address', 'stats-collector'); ?></label></th>
                        <td><input id="sc-url" name="url" type="url" class="regular-text" value="<?php echo esc_attr($s['url']); ?>" placeholder="https://stats.example.org">
                        <p class="description"><?php esc_html_e('Only the address, for example https://stats.example.org.', 'stats-collector'); ?></p></td></tr>
                    <tr><th scope="row"><label for="sc-key"><?php esc_html_e('Site key', 'stats-collector'); ?></label></th>
                        <td><input id="sc-key" name="key" type="text" class="regular-text code" value="<?php echo esc_attr($s['key']); ?>" autocomplete="off"></td></tr>
                    <tr><th scope="row"><label for="sc-secret"><?php esc_html_e('Secret', 'stats-collector'); ?></label></th>
                        <td><input id="sc-secret" name="secret" type="password" class="regular-text code" value="" autocomplete="new-password" placeholder="<?php echo $s['secret'] ? '••••••••' : ''; ?>">
                        <?php if ($s['secret']) : ?><p class="description"><?php esc_html_e('Saved. Leave empty to keep it.', 'stats-collector'); ?></p><?php endif; ?></td></tr>
                </table>

                <h2><?php esc_html_e('What is counted', 'stats-collector'); ?></h2>
                <table class="form-table" role="presentation">
                    <tr><th scope="row"><?php esc_html_e('Content types', 'stats-collector'); ?></th>
                        <td><fieldset>
                            <?php foreach ($types as $type) : ?>
                                <label><input type="checkbox" name="post_types[]" value="<?php echo esc_attr($type->name); ?>" <?php checked(in_array($type->name, $s['post_types'], true)); ?>> <?php echo esc_html($type->labels->name); ?></label><br>
                            <?php endforeach; ?>
                            <p class="description"><?php esc_html_e('The home page is always counted for the site total.', 'stats-collector'); ?></p>
                        </fieldset></td></tr>
                    <tr><th scope="row"><?php esc_html_e('Own visits', 'stats-collector'); ?></th>
                        <td><label><input type="checkbox" name="exclude_editors" value="1" <?php checked($s['exclude_editors']); ?>> <?php esc_html_e('Do not count logged-in editors and administrators', 'stats-collector'); ?></label></td></tr>
                    <tr><th scope="row"><label for="sc-ip"><?php esc_html_e('Behind a proxy or CDN', 'stats-collector'); ?></label></th>
                        <td><select id="sc-ip" name="ip_header">
                            <option value="" <?php selected($s['ip_header'], ''); ?>><?php esc_html_e('No (use the connection address)', 'stats-collector'); ?></option>
                            <?php foreach (array_filter(self::IP_HEADERS) as $h) : ?>
                                <option value="<?php echo esc_attr($h); ?>" <?php selected($s['ip_header'], $h); ?>><?php echo esc_html($h); ?></option>
                            <?php endforeach; ?>
                        </select>
                        <p class="description"><?php esc_html_e('Choose CF-Connecting-IP behind Cloudflare. The address is only used for the daily visitor hash and is never stored.', 'stats-collector'); ?></p></td></tr>
                    <tr><th scope="row"><?php esc_html_e('Editors', 'stats-collector'); ?></th>
                        <td><label><input type="checkbox" name="send_emails" value="1" <?php checked($s['send_emails']); ?>> <?php esc_html_e('Send the email address of authors, so Stats Collector can link them to their account', 'stats-collector'); ?></label></td></tr>
                </table>
                <?php submit_button(__('Save settings', 'stats-collector')); ?>
            </form>

            <h2><?php esc_html_e('Status', 'stats-collector'); ?></h2>
            <table class="widefat striped" style="max-width:720px">
                <tbody>
                    <tr><td><?php esc_html_e('Last batch sent', 'stats-collector'); ?></td><td><?php echo esc_html($fmt($status['last_ok'] ?? null)); ?></td></tr>
                    <tr><td><?php esc_html_e('Last error', 'stats-collector'); ?></td><td><?php echo !empty($status['last_error']) ? esc_html(self::explain((string) $status['last_error']) . ' (' . $fmt($status['last_error_at'] ?? null) . ')') : '–'; ?></td></tr>
                    <tr><td><?php esc_html_e('Next batch', 'stats-collector'); ?></td><td><?php echo esc_html($fmt(wp_next_scheduled('sc_push'))); ?></td></tr>
                    <tr><td><?php esc_html_e('Plugin version', 'stats-collector'); ?></td><td><?php echo esc_html(SC_VERSION); ?></td></tr>
                </tbody>
            </table>
            <p>
                <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>" style="display:inline">
                    <input type="hidden" name="action" value="sc_test"><?php wp_nonce_field('sc_test'); ?>
                    <?php submit_button(__('Test connection', 'stats-collector'), 'secondary', 'submit', false); ?>
                </form>
                <form method="post" action="<?php echo esc_url(admin_url('admin-post.php')); ?>" style="display:inline">
                    <input type="hidden" name="action" value="sc_push"><?php wp_nonce_field('sc_push'); ?>
                    <?php submit_button(__('Send now', 'stats-collector'), 'secondary', 'submit', false); ?>
                </form>
            </p>
            <p class="description"><?php esc_html_e('WordPress runs its scheduled tasks when the site has visitors. For a site with little traffic, let the server call wp-cron.php every minute (see the Stats Collector manual).', 'stats-collector'); ?></p>
        </div>
        <?php
    }
}
