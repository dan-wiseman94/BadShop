# badshop on Windows

## Install the desktop app

Use the Windows x64 installer for a PC with an Intel or AMD 64-bit processor.
You can check yours in **Settings → System → About → System type**.

1. Open [badshop Releases](https://github.com/dan-wiseman94/BadShop/releases).
   When a release is available, expand **Assets** and download the file ending in
   `x64-setup.exe`.
2. If there is no release yet, sign in to GitHub and open the
   [desktop builds for the main branch](https://github.com/dan-wiseman94/BadShop/actions/workflows/desktop.yml?query=branch%3Amain+event%3Apush).
   Click the title of a recent run with a green check. Scroll to **Artifacts** and
   click **badshop-windows-x64**. If the download has expired, try a newer successful run.
3. If you downloaded a ZIP, open **Downloads** in File Explorer, right-click the
   ZIP, choose **Extract All**, and open the extracted folder. Use File Explorer's
   search box to find `*x64-setup.exe` if it is inside another folder.
4. Double-click the setup file and follow the prompts. The current builds are unsigned.
   If Windows shows **Windows protected your PC**, check that the download came from
   this repository. If you trust it and your PC allows it, choose **More info → Run anyway**.
5. Open **Start**, type **badshop**, and launch the app. Follow
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
