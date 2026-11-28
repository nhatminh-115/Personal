#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

mod files;
mod runtime;

use runtime::DesktopRuntime;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::Arc;
use tauri::menu::{Menu, MenuItem, PredefinedMenuItem};
use tauri::tray::{MouseButton, MouseButtonState, TrayIconBuilder, TrayIconEvent};
use tauri::{AppHandle, DragDropEvent, Emitter, Manager, WindowEvent};

struct ExitPolicy(Arc<AtomicBool>);

fn show_main_window(app: &AppHandle) {
    if let Some(window) = app.get_webview_window("main") {
        let _ = window.show();
        let _ = window.unminimize();
        let _ = window.set_focus();
    }
}

fn request_quit(app: AppHandle) {
    let policy = app.state::<ExitPolicy>().0.clone();
    if policy.swap(true, Ordering::SeqCst) {
        return;
    }
    let runtime = app.state::<DesktopRuntime>().inner().clone();
    std::thread::spawn(move || {
        let _ = runtime.stop(&app);
        app.exit(0);
    });
}

fn main() {
    let exit_policy = ExitPolicy(Arc::new(AtomicBool::new(false)));
    tauri::Builder::default()
        .plugin(tauri_plugin_single_instance::init(|app, _args, _cwd| {
            show_main_window(app)
        }))
        .plugin(tauri_plugin_dialog::init())
        .plugin(tauri_plugin_notification::init())
        .plugin(tauri_plugin_global_shortcut::Builder::new().build())
        .plugin(tauri_plugin_window_state::Builder::new().build())
        .plugin(tauri_plugin_autostart::init(
            tauri_plugin_autostart::MacosLauncher::LaunchAgent,
            Some(vec!["--background"]),
        ))
        .manage(DesktopRuntime::default())
        .manage(files::PendingDesktopDrop::default())
        .manage(exit_policy)
        .invoke_handler(tauri::generate_handler![
            runtime::desktop_status,
            runtime::desktop_api_token,
            runtime::desktop_start,
            runtime::desktop_restart,
            runtime::desktop_stop,
            runtime::desktop_save_preferences,
            runtime::desktop_save_windows_preferences,
            runtime::desktop_set_provider_mode,
            runtime::desktop_save_provider_connection,
            runtime::desktop_forget_provider_key,
            runtime::desktop_set_close_to_tray,
            runtime::desktop_create_backup,
            runtime::desktop_restore_backup,
            files::desktop_pick_folder,
            files::desktop_list_folders,
            files::desktop_remove_folder,
            files::desktop_index_folder,
            files::desktop_get_folder_index_snapshot,
            files::desktop_search_folder_indexes,
            files::desktop_list_folder_entries,
            files::desktop_read_folder_file,
            files::desktop_consume_dropped_files,
        ])
        .setup(|app| {
            let runtime = app.state::<DesktopRuntime>().inner().clone();
            runtime.apply_preferences(DesktopRuntime::load_preferences(app.handle()));

            if std::env::args().any(|argument| argument == "--background") {
                if let Some(window) = app.get_webview_window("main") {
                    let _ = window.hide();
                }
            }

            let show = MenuItem::with_id(app, "show", "Show Kuractus", true, None::<&str>)?;
            let start = MenuItem::with_id(app, "start", "Start Kuractus", true, None::<&str>)?;
            let logs = MenuItem::with_id(app, "logs", "Open runtime settings", true, None::<&str>)?;
            let separator = PredefinedMenuItem::separator(app)?;
            let quit = MenuItem::with_id(app, "quit", "Quit Kuractus", true, None::<&str>)?;
            let menu = Menu::with_items(app, &[&show, &start, &logs, &separator, &quit])?;
            let icon = app
                .default_window_icon()
                .cloned()
                .ok_or("Kuractus tray icon is missing")?;
            TrayIconBuilder::with_id("aura-tray")
                .icon(icon)
                .tooltip("Kuractus Personal")
                .menu(&menu)
                .show_menu_on_left_click(false)
                .on_menu_event(|app, event| match event.id().as_ref() {
                    "show" => show_main_window(app),
                    "start" => {
                        let runtime = app.state::<DesktopRuntime>().inner().clone();
                        let app_for_thread = app.clone();
                        std::thread::spawn(move || {
                            let _ = runtime.start(&app_for_thread);
                        });
                        show_main_window(app);
                    }
                    "logs" => {
                        show_main_window(app);
                        let _ = app.emit("desktop:open-settings", ());
                    }
                    "quit" => request_quit(app.clone()),
                    _ => {}
                })
                .on_tray_icon_event(|tray, event| {
                    if let TrayIconEvent::Click {
                        button: MouseButton::Left,
                        button_state: MouseButtonState::Up,
                        ..
                    } = event
                    {
                        show_main_window(tray.app_handle());
                    }
                })
                .build(app)?;

            // The UI opens even if Docker is stopped; the runtime panel reports
            // the exact prerequisite and offers a retry.
            let app_handle = app.handle().clone();
            std::thread::spawn(move || {
                let _ = runtime.start(&app_handle);
            });
            Ok(())
        })
        .on_window_event(|window, event| match event {
            WindowEvent::DragDrop(DragDropEvent::Drop { paths, .. })
                if window.label() == "main" =>
            {
                let app = window.app_handle();
                let pending = app.state::<files::PendingDesktopDrop>();
                if pending.capture(paths.clone()).is_ok() {
                    let _ = app.emit("desktop:files-dropped", ());
                } else {
                    let _ = app.emit("desktop:file-drop-rejected", ());
                }
            }
            WindowEvent::CloseRequested { api, .. } => {
                api.prevent_close();
                let app = window.app_handle().clone();
                let should_tray = app.state::<DesktopRuntime>().snapshot().close_to_tray;
                if should_tray {
                    let _ = window.hide();
                } else {
                    request_quit(app);
                }
            }
            _ => {}
        })
        .run(tauri::generate_context!())
        .expect("Kuractus Desktop failed to start");
}
