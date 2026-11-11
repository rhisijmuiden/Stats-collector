<?php
/**
 * Plugin Name:       Stats Collector
 * Description:       Cookieless page views, visitors, reading time and share clicks per article, sent every minute to your Stats Collector.
 * Version:           0.3.1
 * Requires at least: 6.5
 * Requires PHP:      8.1
 * Author:            Stats Collector
 * License:           MIT
 * Text Domain:       stats-collector
 * Domain Path:       /languages
 */

defined('ABSPATH') || exit;

define('SC_VERSION', '0.3.1');
define('SC_FILE', __FILE__);
define('SC_DIR', plugin_dir_path(__FILE__));

require_once SC_DIR . 'includes/class-sc-store.php';
require_once SC_DIR . 'includes/class-sc-tracker.php';
require_once SC_DIR . 'includes/class-sc-sender.php';
require_once SC_DIR . 'includes/class-sc-admin.php';

register_activation_hook(__FILE__, ['SC_Store', 'install']);
register_activation_hook(__FILE__, ['SC_Sender', 'schedule']);
register_deactivation_hook(__FILE__, ['SC_Sender', 'unschedule']);

add_action('plugins_loaded', static function () {
    load_plugin_textdomain('stats-collector', false, dirname(plugin_basename(SC_FILE)) . '/languages');
    SC_Store::maybe_upgrade();
    SC_Tracker::init();
    SC_Sender::init();
    if (is_admin()) {
        SC_Admin::init();
    }
});
