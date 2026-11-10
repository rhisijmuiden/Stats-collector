<?php
// Removes the plugin's tables and settings when it is deleted in WordPress.
defined('WP_UNINSTALL_PLUGIN') || exit;

global $wpdb;
$wpdb->query("DROP TABLE IF EXISTS {$wpdb->prefix}sc_views");
foreach (['sc_settings', 'sc_db_version', 'sc_salt', 'sc_status'] as $option) {
    delete_option($option);
}
wp_clear_scheduled_hook('sc_push');
wp_clear_scheduled_hook('sc_cleanup');
