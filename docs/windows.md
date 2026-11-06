# badshop on Windows

## Install the desktop app

Use the Windows x64 installer for a PC with an Intel or AMD 64-bit processor.
You can check yours in **Settings → System → About → System type**.

1. [Download the Windows installer](https://github.com/dan-wiseman94/BadShop/releases/download/desktop-v0.1.0/badshop_0.1.0_x64-setup.exe).
2. Open **Downloads** in File Explorer and double-click `badshop_0.1.0_x64-setup.exe`.
   Follow the setup prompts. This release is unsigned.
   If Windows shows **Windows protected your PC**, check that the download came from
   this repository. If you trust it and your PC allows it, choose **More info → Run anyway**.
3. Open **Start**, type **badshop**, and launch the app. Follow
   [Make your first edit](../README.md#make-your-first-edit) to try an effect and save a picture.

**Downloaded “Source code” or “Code → Download ZIP”?** That ZIP contains the project files.
Use the installer instructions above for the ready-to-run app, or follow the source setup below.

## Run from source

Use this route if you want to work with the source files or try a change before an installer is built.
Start with an extracted copy in a short local path such as `C:\src\badshop`.

1. Install **Microsoft C++ Build Tools**. In Visual Studio Installer, select **Desktop
   development with C++**, including the MSVC x64 compiler and Windows SDK. Tauri also
   needs **Microsoft Edge WebView2 Runtime**, normally included with Windows 10 and 11.
   See [Tauri's Windows prerequisites](https://v2.tauri.app/start/prerequisites/#windows).
2. Install [Rust](https://rustup.rs/) using the default stable MSVC toolchain, and
   install [Node.js 22 for Windows x64](https://nodejs.org/dist/latest-v22.x/) using
   the `.msi` installer. Keep npm selected.
3. Open a new PowerShell window. Run each line below. uv will download Python 3.12
   for badshop when needed. If your PC lacks the `winget` command, use the
   [uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).

   ```powershell
   winget install --exact --id astral-sh.uv
   npm.cmd install --global pnpm@10
   ```

4. In File Explorer, open the extracted folder containing `README.md` and double-click
   **start.cmd**. From a terminal in that folder, you can also run `.\start.cmd`.
   The first run downloads dependencies and builds the app. Keep the command window
   open while editing. Close badshop to finish.

| If you see this | What to do |
| --- | --- |
| “Missing” followed by a tool name | Finish the corresponding install above, then open a fresh terminal and run the launcher again. Cargo comes with Rust. |
| A build error mentioning `link.exe` or the Windows SDK | Open Visual Studio Installer, choose **Modify**, and check the C++ workload and SDK in step 1. |
| A message that port 1420 is in use | Close your other badshop development session and try again. |
| An error during a download | Check your connection and rerun the launcher. Completed downloads are cached. |

For more details, see [development and testing](development.md).
