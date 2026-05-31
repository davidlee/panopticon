// Panopticon content-extraction script. Injected by the background
// script into pages the user has dwelled on for 30+ seconds.
// Runs Mozilla Readability on a cloned DOM and sends the extracted
// article object back to the background script.

(function () {
  try {
    var doc = document.cloneNode(true);
    var article = new Readability(doc).parse();

    if (!article) {
      browser.runtime.sendMessage({
        type: "content_extracted",
        url: location.href,
        error: "readability_returned_null",
      });
      return;
    }

    browser.runtime.sendMessage({
      type: "content_extracted",
      url: location.href,
      title: article.title,
      byline: article.byline || null,
      excerpt: article.excerpt || null,
      siteName: article.siteName || null,
      publishedTime: article.publishedTime || null,
      textContent: article.textContent,
      contentHtml: article.content,
      length: article.length,
      capturedAt: new Date().toISOString(),
    });
  } catch (e) {
    browser.runtime.sendMessage({
      type: "content_extracted",
      url: location.href,
      error: e.message,
    });
  }
})();
