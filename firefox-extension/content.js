// Panopticon content-extraction script. Injected by the background script
// (dwell timer and the manual "Extract page content" menu item), then
// called directly: `executeScript({func: () => panopticonExtract()})`
// returns the article object to the awaiting caller. No runtime message.

function panopticonExtract() {
  try {
    var doc = document.cloneNode(true);
    var article = new Readability(doc).parse();

    if (!article) {
      return { url: location.href, error: "readability_returned_null" };
    }

    return {
      url: location.href,
      title: article.title,
      byline: article.byline || null,
      excerpt: article.excerpt || null,
      siteName: article.siteName || null,
      publishedTime: article.publishedTime || null,
      textContent: article.textContent,
      contentHtml: article.content,
      length: article.length,
    };
  } catch (e) {
    return { url: location.href, error: e.message };
  }
}
