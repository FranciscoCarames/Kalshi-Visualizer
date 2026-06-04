# Presence of this file makes the project root pytest's rootdir, so tests can
# `import data` / `import consistency` directly.
#
# Load NiceGUI's HEADLESS user-simulation plugin (no selenium) so the dashboard browser smoke tests
# (tests/test_browser.py) get the async `user` fixture + the `nicegui_main_file` marker. This is the
# no-selenium plugin specifically (not nicegui.testing.plugin, which pulls in selenium/webdriver).
pytest_plugins = ["nicegui.testing.user_plugin"]
