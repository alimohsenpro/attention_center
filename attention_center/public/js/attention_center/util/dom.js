// Adds a stylesheet to the shadow root: an adopted sheet where the browser supports it, else a <style> element.
export function adoptStyles(root, css) {
	if ("adoptedStyleSheets" in root && "replaceSync" in CSSStyleSheet.prototype) {
		const sheet = new CSSStyleSheet();
		sheet.replaceSync(css);
		root.adoptedStyleSheets = [...root.adoptedStyleSheets, sheet];
	} else {
		const style = document.createElement("style");
		style.textContent = css;
		root.append(style);
	}
}
