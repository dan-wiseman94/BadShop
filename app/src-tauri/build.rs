fn main() {
    println!("cargo:rerun-if-env-changed=BADSHOP_UPDATER_PUBLIC_KEY");
    tauri_build::build()
}
