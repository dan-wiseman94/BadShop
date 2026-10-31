//! Route AppKit Quit (including Dock/OS requests) through the unsaved-project guard.
use objc2::{
    ffi::class_addMethod,
    msg_send,
    rc::Retained,
    runtime::{AnyClass, AnyObject, Imp, Sel},
    sel,
};
use std::sync::OnceLock;
use tauri::Manager;

static APP: OnceLock<tauri::AppHandle> = OnceLock::new();

unsafe extern "C-unwind" fn should_terminate(
    _delegate: *mut AnyObject,
    _selector: Sel,
    _application: *mut AnyObject,
) -> usize {
    if let Some(window) = APP.get().and_then(|app| app.get_webview_window("main")) {
        // AppKit must not quit while the asynchronous frontend decides. If approved,
        // the frontend destroys the last window and Tauri exits normally.
        match window.close() {
            Ok(()) => eprintln!("badshop: native Quit routed through project close guard"),
            Err(error) => eprintln!("badshop: could not request project close: {error}"),
        }
        0 // NSTerminateCancel
    } else {
        1 // NSTerminateNow
    }
}

pub fn install(app: &tauri::AppHandle) -> Result<(), Box<dyn std::error::Error>> {
    APP.set(app.clone())
        .map_err(|_| "Quit guard already installed")?;
    // Setup runs on the main thread after Tao installs its delegate. Add only the
    // optional termination decision; retain Tao's existing lifecycle callbacks.
    unsafe {
        let class = AnyClass::get(c"NSApplication").ok_or("NSApplication unavailable")?;
        let application: *mut AnyObject = msg_send![class, sharedApplication];
        let delegate: *mut AnyObject = msg_send![application, delegate];
        let delegate = Retained::retain(delegate).ok_or("Application delegate unavailable")?;
        let callback: unsafe extern "C-unwind" fn(*mut AnyObject, Sel, *mut AnyObject) -> usize =
            should_terminate;
        let added = class_addMethod(
            delegate.class() as *const AnyClass as *mut AnyClass,
            sel!(applicationShouldTerminate:),
            std::mem::transmute::<_, Imp>(callback),
            // NSApplicationTerminateReply is NSUInteger on supported 64-bit Macs.
            c"Q@:@".as_ptr(),
        );
        if !added.as_bool() {
            return Err("Application delegate already implements its own Quit decision".into());
        }
        // AppKit can cache optional delegate selectors. Refresh its registration
        // after adding ours; hold a strong reference and restore the identical object.
        let _: () = msg_send![application, setDelegate: std::ptr::null::<AnyObject>()];
        let _: () = msg_send![application, setDelegate: &*delegate];
    }
    Ok(())
}
