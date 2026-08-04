# Jarvis Desktop (Tauri v2)

Native shell around the `apps/web` PWA. **There is no frontend in this package.**
`src-tauri/tauri.conf.json` runs `apps/web` for both dev (`beforeDevCommand`, `devUrl`)
and release (`beforeBuildCommand`, `frontendDist: ../../web/dist`).

## Commands

```sh
npm install        # installs @tauri-apps/cli only
npm run dev        # tauri dev  -> boots apps/web on :5173, then the native window
npm run build      # tauri build -> builds apps/web, then bundles the installer
```

Rust-only sanity check: `cargo check` inside `src-tauri/`.

## Behaviour

- **Tray**: left click or "Mostrar Jarvis" reveals the window; "Sair" quits.
- **Single instance**: `tauri-plugin-single-instance` focuses the running window
  instead of opening a duplicate (important because autostart is enabled).
- **Hidden autostart**: the window is declared `"visible": false`. `setup()` shows it
  on every manual launch, but skips that when the process was started with
  `--minimized` — the flag `tauri-plugin-autostart` registers with the OS. So a
  login-triggered start lands silently in the tray.
- **Close button**: intercepted in `apps/web/src/hooks/useDesktopIntegration.ts`,
  which asks whether to quit or minimize to tray.

## Dark chrome (Plano A / D4)

Two fields in the `main` window config carry the whole thing — no Rust, no HTML:

- `"backgroundColor": "#101a24"` — painted by the window layer *and* by WebView2
  (`from_config` feeds both `WindowBuilder` and `WebviewAttributes`), so there is no
  white flash between `show()` and the first paint of the web app.
- `"theme": "Dark"` — on Windows `tao` turns this into
  `DwmSetWindowAttribute(DWMWA_USE_IMMERSIVE_DARK_MODE)` at window creation, giving a
  dark system title bar, and `tauri-runtime-wry` forwards the same theme to
  `ICoreWebView2_13::SetPreferredColorScheme`, so the page boots with
  `prefers-color-scheme: dark`.

`titleBarStyle` is **macOS only** in Tauri v2 — it does nothing here. `decorations: false`
was rejected on purpose: it would kill native snap/drag/resize and require a
`data-tauri-drag-region` header inside `apps/web`.

Forcing the theme means the desk shell always reports dark to the web app, whatever the
OS is set to. If the web app ever needs to follow the system again, drop `theme` and set
it at runtime instead.

## Known gap

The tray still uses `app.default_window_icon()`, i.e. the bundled `icons/*.png`, which
are the stock Tauri logo (yellow/cyan). That clashes with the dark steel UI. A
monochrome mark is needed; there is no brand asset in this package to derive one from.

## Permissions

Anything the web app calls over IPC needs a permission in `src-tauri/capabilities/`.
`desktop.json` covers the APIs used by `useDesktopIntegration.ts`. Note that
`dialog:default` does **not** include `ask`, and `global-shortcut:default` is empty —
both must be granted per command.
