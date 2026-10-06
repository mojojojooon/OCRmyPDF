<!-- SPDX-FileCopyrightText: 2026 OCRmyPDF contributors -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 -->

# OCRmyPDF desktop app

A small window on top of OCRmyPDF. Drop a scanned PDF on it and it writes a searchable PDF next to the original. The original file is not changed.

The window calls the Python function `ocrmypdf.ocr`. It does not replace the `ocrmypdf` command.

## What you need

OCRmyPDF reads pages with **Tesseract OCR** and uses **Ghostscript** for some PDF conversions. Install both before you open the app. Python 3.11 or newer is required.

### Windows

1. Install Tesseract (64-bit) and Ghostscript (64-bit).

   With [winget](https://learn.microsoft.com/en-us/windows/package-manager/winget/):

   ```powershell
   winget install -e --id tesseract-ocr.tesseract
   ```

   Ghostscript is not in winget. Download the 64-bit installer from the [Ghostscript download page](https://ghostscript.com/releases/gsdnld.html) and run it.

   Or, in an Administrator command prompt, with [Chocolatey](https://chocolatey.org/):

   ```powershell
   choco install tesseract
   choco install ghostscript
   ```

2. Install Python 3.11 or newer from [python.org](https://www.python.org/downloads/windows/) if you do not already have it. Enable **Add python.exe to PATH** in the installer.

3. Open a **new** PowerShell or Command Prompt window, so the installers are on `PATH`, and install the app from a checkout of this repository:

   ```powershell
   cd path\to\OCRmyPDF
   py -m pip install -e ".[gui]"
   ```

   `py` is the Python launcher. `python -m pip install -e ".[gui]"` does the same thing when `python` is on `PATH`.

4. Start the window:

   ```powershell
   ocrmypdf-gui
   ```

   Or:

   ```powershell
   py -m ocrmypdf_gui
   ```

If the app says Tesseract or Ghostscript is missing, close it, open a new terminal, and run `tesseract --version` and `gswin64c --version`. OCRmyPDF also looks in the Windows Registry and the usual Program Files folders, so a normal installer is enough even when those commands are not on `PATH`.

Other Tesseract languages are optional. The English data is included with the usual Windows installer. Extra languages are `.traineddata` files in Tesseract's `tessdata` folder. The language menu lists what Tesseract reports.

### macOS and Linux

Install Tesseract and Ghostscript the same way you would for the `ocrmypdf` command (Homebrew: `brew install tesseract ghostscript`; Debian/Ubuntu: `sudo apt install tesseract-ocr ghostscript`). Then:

```bash
pip install -e ".[gui]"
ocrmypdf-gui
```

## Using the window

- Drag one or more PDFs onto the window, or click **Choose files**.
- Each file is processed in the background. The list shows progress for the file that is running, and an error on a file that fails.
- Options, applied when a file starts:
  - **Language** defaults to English (`eng`). You can type a Tesseract code, or combine codes as `eng+fra`.
  - **Deskew** straightens a crooked scan.
  - **Rotate pages** turns pages that are sideways.
  - **Skip pages that already have text** is on by default. Pages that already contain text are copied through unchanged. If you turn it off and the PDF already has text, the app asks whether to skip those pages or force OCR.
- The result is `<name>_searchable.pdf` in the same folder as the original. If that name is taken, the app uses `<name>_searchable_2.pdf` and so on. The original is not overwritten.
- When a file is ready, **Open** and **Show in folder** open it or its folder. The bar at the bottom of the window does the same for the latest file.

## Standalone build (PyInstaller)

This is optional. The `ocrmypdf-gui` command is enough for normal use.

The repository already ships a PyInstaller hook for OCRmyPDF. From the repository root, with PyInstaller installed (`pip install pyinstaller`):

```powershell
py -m pip install -e ".[gui]" pyinstaller
py desktop_app\build_app.py
```

On macOS or Linux, use `python desktop_app/build_app.py`.

The build writes `dist/OCRmyPDF/`. Run `dist\OCRmyPDF\OCRmyPDF.exe` on Windows. Tesseract and Ghostscript are **not** inside that folder; install them as above. The spec file is `desktop_app/ocrmypdf-gui.spec` if you want to change the build.
