# Send image to badshop

For Chromium browsers, enable Developer mode on the Extensions page, choose **Load unpacked**, and select this folder. Requires Chromium 116 or later. This is a local development extension, not a published store listing.

Right-click an image and choose **Send image to badshop (copy)**. The extension badge says COPY when the source card is ready. Switch to badshop and paste it into chat, or into **Images & directions → Image URL or browser source card**. badshop imports the selected image with its source page attached.

The helper requests context-menu, offscreen-document, and clipboard-write permissions. It does not read clipboard content, inject page scripts, request broad website access, or connect to the local core. The copy replaces clipboard text only after an explicit menu click. Hover its toolbar icon for error details.

Only HTTP(S) images can be fetched this way. For blob URLs, authenticated image downloads, or pages blocking downloads, copy the image pixels and paste them into badshop instead. A page title is a label, not a verified creator or license; the helper leaves those unknown.
