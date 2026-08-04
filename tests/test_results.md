# 测试结果

- 运行时间：2026-08-04T11:40:51
- 用例数：65
- 通过：65
- 失败：0
- 错误：0

## 输出

```text
test_builds_campus_tools (test_agent.CampusAgentTests.test_builds_campus_tools) ... ok
test_builds_subagents_and_covers_all_tools (test_agent.CampusAgentTests.test_builds_subagents_and_covers_all_tools) ... ok
test_create_reminder_tool (test_agent.CampusAgentTests.test_create_reminder_tool) ... ok
test_default_tool_limit_is_ten (test_agent.CampusAgentTests.test_default_tool_limit_is_ten) ... ok
test_empty_input (test_agent.CampusAgentTests.test_empty_input) ... ok
test_history_and_persistence (test_agent.CampusAgentTests.test_history_and_persistence) ... ok
test_llm_failure_returns_error (test_agent.CampusAgentTests.test_llm_failure_returns_error) ... ok
test_md_to_text_plain (test_agent.CampusAgentTests.test_md_to_text_plain) ... ok
test_search_tool (test_agent.CampusAgentTests.test_search_tool) ... ok
test_create_event_auto_id (test_event_store.EventStoreTests.test_create_event_auto_id) ... ok
test_create_event_invalid_duration (test_event_store.EventStoreTests.test_create_event_invalid_duration) ... ok
test_create_event_requires_fields (test_event_store.EventStoreTests.test_create_event_requires_fields) ... ok
test_create_event_with_duration (test_event_store.EventStoreTests.test_create_event_with_duration) ... ok
test_data_validation (test_event_store.EventStoreTests.test_data_validation) ... ok
test_delete_event (test_event_store.EventStoreTests.test_delete_event) ... ok
test_display_fields (test_event_store.EventStoreTests.test_display_fields) ... ok
test_filter_by_category (test_event_store.EventStoreTests.test_filter_by_category) ... ok
test_filter_by_time_range (test_event_store.EventStoreTests.test_filter_by_time_range) ... ok
test_legacy_end_time_migration (test_event_store.EventStoreTests.test_legacy_end_time_migration) ... ok
test_mixed_time_formats (test_event_store.EventStoreTests.test_mixed_time_formats) ... ok
test_search_by_keyword (test_event_store.EventStoreTests.test_search_by_keyword) ... ok
test_update_event (test_event_store.EventStoreTests.test_update_event) ... ok
test_update_event_duration (test_event_store.EventStoreTests.test_update_event_duration) ... ok
test_any_one_match_is_enough (test_interest_matcher.InterestMatcherTests.test_any_one_match_is_enough) ... ok
test_category_match_records_matched_tag (test_interest_matcher.InterestMatcherTests.test_category_match_records_matched_tag) ... ok
test_interest_agent_batch_push (test_interest_matcher.InterestMatcherTests.test_interest_agent_batch_push) ... ok
test_match_and_push (test_interest_matcher.InterestMatcherTests.test_match_and_push) ... ok
test_no_duplicate_push (test_interest_matcher.InterestMatcherTests.test_no_duplicate_push) ... ok
test_no_match_no_push (test_interest_matcher.InterestMatcherTests.test_no_match_no_push) ... ok
test_notifications_for_filters_user (test_interest_matcher.InterestMatcherTests.test_notifications_for_filters_user) ... ok
test_reload_reads_external_preferences (test_interest_matcher.InterestMatcherTests.test_reload_reads_external_preferences) ... ok
test_remove_by_event (test_interest_matcher.InterestMatcherTests.test_remove_by_event) ... ok
test_status_reports_any_tag_rule (test_interest_matcher.InterestMatcherTests.test_status_reports_any_tag_rule) ... ok
test_extract_first_page (test_njfu_feed.NJFUFixtureTests.test_extract_first_page) ... ok
test_missing_data_list_raises (test_njfu_feed.NJFUFixtureTests.test_missing_data_list_raises) ... ok
test_summary_fields (test_njfu_feed.NJFUFixtureTests.test_summary_fields) ... ok
test_run_adds_good_and_queues_bad (test_njfu_feed.SchoolHtmlScraperTests.test_run_adds_good_and_queues_bad) ... ok
test_second_run_keeps_pending_once (test_njfu_feed.SchoolHtmlScraperTests.test_second_run_keeps_pending_once) ... ok
test_cancel_by_event_deletes (test_reminders.ReminderStoreTests.test_cancel_by_event_deletes) ... ok
test_cancel_deletes_reminder (test_reminders.ReminderStoreTests.test_cancel_deletes_reminder) ... ok
test_check_due_marks_notified_once (test_reminders.ReminderStoreTests.test_check_due_marks_notified_once) ... ok
test_complete_deletes_reminder (test_reminders.ReminderStoreTests.test_complete_deletes_reminder) ... ok
test_prune_keeps_recent_notified (test_reminders.ReminderStoreTests.test_prune_keeps_recent_notified) ... ok
test_prune_removes_stale_done_and_cancelled (test_reminders.ReminderStoreTests.test_prune_removes_stale_done_and_cancelled) ... ok
test_prune_removes_stale_notified (test_reminders.ReminderStoreTests.test_prune_removes_stale_notified) ... ok
test_retention_disabled_keeps_everything (test_reminders.ReminderStoreTests.test_retention_disabled_keeps_everything) ... ok
test_scheduler_check_now_uses_store (test_reminders.ReminderStoreTests.test_scheduler_check_now_uses_store) ... ok
test_deduplication (test_scraper.ScraperTests.test_deduplication) ... ok
test_manual_review (test_scraper.ScraperTests.test_manual_review) ... ok
test_run_adds_and_rejects_bad_record (test_scraper.ScraperTests.test_run_adds_and_rejects_bad_record) ... ok
test_chinese_month_day (test_time_parser.TimeParserTests.test_chinese_month_day) ... ok
test_dotted_date (test_time_parser.TimeParserTests.test_dotted_date) ... ok
test_evening_time (test_time_parser.TimeParserTests.test_evening_time) ... ok
test_iso_datetime (test_time_parser.TimeParserTests.test_iso_datetime) ... ok
test_next_month_day (test_time_parser.TimeParserTests.test_next_month_day) ... ok
test_next_week_weekday (test_time_parser.TimeParserTests.test_next_week_weekday) ... ok
test_parse_duration_invalid (test_time_parser.TimeParserTests.test_parse_duration_invalid) ... ok
test_parse_duration_variants (test_time_parser.TimeParserTests.test_parse_duration_variants) ... ok
test_range_next_month (test_time_parser.TimeParserTests.test_range_next_month) ... ok
test_range_this_week (test_time_parser.TimeParserTests.test_range_this_week) ... ok
test_semester_week (test_time_parser.TimeParserTests.test_semester_week) ... ok
test_this_month_day (test_time_parser.TimeParserTests.test_this_month_day) ... ok
test_this_week_friday (test_time_parser.TimeParserTests.test_this_week_friday) ... ok
test_tomorrow (test_time_parser.TimeParserTests.test_tomorrow) ... ok
test_weekday_afternoon (test_time_parser.TimeParserTests.test_weekday_afternoon) ... ok

----------------------------------------------------------------------
Ran 65 tests in 3.139s

OK

```
