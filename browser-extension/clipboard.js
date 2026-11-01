chrome.runtime.onMessage.addListener((message, sender, respond) => {
  if (sender.id !== chrome.runtime.id || message.target !== "badshop-clipboard")
    return;
  try {
    const input = document.querySelector("#clipboard");
    input.value = message.text;
    input.select();
    // The asynchronous Clipboard API requires focus; offscreen documents have none.
    if (!document.execCommand("copy"))
      throw new Error(
        "Could not copy the image source. Try Copy image address instead.",
      );
    input.value = "";
    respond({ ok: true });
  } catch (error) {
    respond({ ok: false, error: String(error.message || error) });
  }
});
