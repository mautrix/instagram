# mautrix-instagram - A Matrix-Instagram puppeting bridge.
# Copyright (C) 2020 Tulir Asokan
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.
from typing import Dict, Any

from .base import BaseAndroidAPI

pre_login_configs = ("ig_fbns_blocked,ig_android_felix_release_players,"
                     "ig_user_mismatch_soft_error,ig_android_carrier_signals_killswitch,"
                     "ig_android_killswitch_perm_direct_ssim,fizz_ig_android,"
                     "ig_mi_block_expired_events,ig_android_os_version_blocking_config")
post_login_configs = ("ig_android_insights_welcome_dialog_tooltip,"
                      "ig_android_extra_native_debugging_info,"
                      "ig_android_insights_top_account_dialog_tooltip,"
                      "ig_android_explore_startup_prefetch_launcher,"
                      "ig_android_newsfeed_recyclerview,ig_android_react_native_ota_kill_switch,"
                      "ig_qe_value_consistency_checker,"
                      "ig_android_qp_keep_promotion_during_cooldown,"
                      "ig_launcher_ig_explore_post_chaining_hide_comments_android_v0,"
                      "ig_android_video_playback,"
                      "ig_launcher_ig_android_network_stack_queue_undefined_request_qe,"
                      "ig_camera_android_attributed_effects_endpoint_api_query_config,"
                      "ig_android_notification_setting_sync,ig_android_dogfooding,"
                      "ig_launcher_ig_explore_post_chaining_pill_android_v0,"
                      "ig_android_request_compression_launcher,ig_delink_lasso_accounts,"
                      "ig_android_stories_send_preloaded_reels_with_reels_tray,"
                      "ig_android_critical_path_manager,"
                      "ig_android_shopping_django_product_search,ig_android_qp_surveys_v1,"
                      "ig_android_feed_attach_report_logs,ig_android_uri_parser_cache_launcher,"
                      "ig_android_global_scheduler_infra,ig_android_explore_grid_viewpoint,"
                      "ig_android_global_scheduler_direct,ig_android_upload_heap_on_oom,"
                      "ig_launcher_ig_android_network_stack_cap_api_request_qe,"
                      "ig_android_async_view_model_launcher,ig_android_bug_report_screen_record,"
                      "ig_canvas_ad_pixel,ig_android_bloks_demos,"
                      "ig_launcher_force_switch_on_dialog,ig_story_insights_entry,"
                      "ig_android_executor_limit_per_group_config,"
                      "ig_android_bitmap_strong_ref_cache_layer_launcher,"
                      "ig_android_cold_start_class_preloading,"
                      "ig_direct_e2e_send_waterfall_sample_rate_config,"
                      "ig_android_qp_waterfall_logging,ig_synchronous_account_switch,"
                      "ig_launcher_ig_android_reactnative_realtime_ota,"
                      "ig_contact_invites_netego_killswitch,"
                      "ig_launcher_ig_explore_video_chaining_container_module_android,"
                      "ig_launcher_ig_explore_remove_topic_channel_tooltip_experiment_android,"
                      "ig_android_request_cap_tuning_with_bandwidth,"
                      "ig_android_rageshake_redesign,"
                      "ig_launcher_explore_navigation_redesign_android,"
                      "ig_android_betamap_cold_start,ig_android_employee_options,"
                      "ig_android_direct_gifs_killswitch,ig_android_gps_improvements_launcher,"
                      "ig_launcher_ig_android_network_stack_cap_video_request_qe,"
                      "ig_launcher_ig_android_network_request_cap_tuning_qe,"
                      "ig_android_qp_xshare_to_fb,ig_android_feed_report_ranking_issue,"
                      "ig_launcher_ig_explore_verified_badge_android,"
                      "ig_android_bloks_data_release,ig_android_feed_camera_latency")


class LauncherSyncAPI(BaseAndroidAPI):
    async def launcher_pre_login_sync(self):
        await self.__sync({
            "id": self.state.device.uuid,
            "configs": pre_login_configs,
        })

    async def launcher_post_login_sync(self):
        await self.__sync({
            "_csrftoken": self.state.cookies.csrf_token,
            "id": self.state.cookies.user_id,
            "_uid": self.state.cookies.user_id,
            "_uuid": self.state.device.uuid,
            "configs": post_login_configs,
        })

    async def __sync(self, req: Dict[str, Any]):
        # TODO parse response?
        return await self.std_http_post("/api/v1/launcher/sync/", data=req)
