use tauri::Manager;

/// Flag appended to the autostart registration (see `tauri_plugin_autostart` setup below).
/// When the OS launches Jarvis on login it passes this argument, and we keep the window
/// hidden so the app only lives in the tray. The window is declared `"visible": false`
/// in `tauri.conf.json`, and `setup` shows it explicitly for every *manual* launch.
const AUTOSTART_FLAG: &str = "--minimized";

fn started_from_autostart() -> bool {
    std::env::args().any(|arg| arg == AUTOSTART_FLAG)
}

fn reveal_main_window(app: &tauri::AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

#[cfg_attr(mobile, tauri::mobile_entry_point)]
pub fn run() {
    let builder = tauri::Builder::default();

    // Must be registered before every other plugin so a second process bails out early.
    #[cfg(desktop)]
    let builder = builder.plugin(tauri_plugin_single_instance::init(|app, _argv, _cwd| {
        // A second instance was launched: focus the one already running instead.
        reveal_main_window(app);
    }));

    builder
        .plugin(tauri_plugin_dialog::init())
        .plugin(
            tauri_plugin_autostart::Builder::new()
                .args([AUTOSTART_FLAG])
                .build(),
        )
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_opener::init())
        .setup(|app| {
            use tauri::menu::{Menu, MenuItem};
            use tauri::tray::TrayIconBuilder;

            let show_i = MenuItem::with_id(app, "show", "Mostrar Jarvis", true, None::<&str>)?;
            let quit_i = MenuItem::with_id(app, "quit", "Sair", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show_i, &quit_i])?;

            let mut tray = TrayIconBuilder::new();
            if let Some(icon) = app.default_window_icon() {
                tray = tray.icon(icon.clone());
            }

            tray.tooltip("Jarvis")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id.as_ref() {
                    "quit" => {
                        app.exit(0);
                    }
                    "show" => {
                        reveal_main_window(app);
                    }
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let tauri::tray::TrayIconEvent::Click {
                        button: tauri::tray::MouseButton::Left,
                        button_state: tauri::tray::MouseButtonState::Up,
                        ..
                    } = event
                    {
                        reveal_main_window(tray.app_handle());
                    }
                })
                .build(app)?;

            // The window starts hidden (tauri.conf.json). Only a manual launch reveals it;
            // an autostart launch stays in the tray until the user asks for it.
            if !started_from_autostart() {
                reveal_main_window(app.handle());
            }

            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running tauri application");
}
