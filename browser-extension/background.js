/* No page access or desktop credentials: only the image the user explicitly selects. */
chrome.runtime.onInstalled.addListener(() => {
  chrome.contextMenus.removeAll(() => {
    chrome.contextMenus.create({
      id: "badshop-image",
      title: "Send image to badshop (copy)",
      contexts: ["image"],
    });
  });
});
let creating;
async function clipboardDocument() {
  const contexts = await chrome.runtime.getContexts({
    contextTypes: ["OFFSCREEN_DOCUMENT"],
    documentUrls: [chrome.runtime.getURL("clipboard.html")],
  });
  if (contexts.length) return;
  if (!creating)
    creating = chrome.offscreen
      .createDocument({
        url: "clipboard.html",
        reasons: ["CLIPBOARD"],
        justification:
          "Copy the image selected by the user and its source page for pasting into badshop.",
      })
      .finally(() => {
        creating = undefined;
      });
  await creating;
}
// Serialize rapid clicks so the clipboard always ends with the last selected image.
let queue = Promise.resolve();
chrome.contextMenus.onClicked.addListener((info, tab) => {
  if (info.menuItemId !== "badshop-image") return;
  queue = queue
    .then(async () => {
      if (!/^https?:\/\//i.test(info.srcUrl ?? ""))
        throw new Error(
          "This image has no public HTTP image URL. Copy the image itself and paste it into badshop.",
        );
      await clipboardDocument();
      const response = await chrome.runtime.sendMessage({
        target: "badshop-clipboard",
        text: JSON.stringify({
          badshop_source: 1,
          url: info.srcUrl,
          page: info.frameUrl || info.pageUrl,
          title: tab?.title || "Selected web image",
        }),
      });
      if (!response?.ok)
        throw new Error(response?.error || "Clipboard copy failed");
      await chrome.action.setBadgeText({ text: "COPY" });
      await chrome.action.setTitle({
        title: "Image copied. Paste into badshop to import it.",
      });
    })
    .catch(async (error) => {
      await chrome.action.setBadgeText({ text: "!" });
      await chrome.action.setTitle({ title: String(error.message || error) });
    });
});
