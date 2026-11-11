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

// A new element with an optional class and text; the text is set as text, never parsed as HTML.
export function element(tag, className, text) {
	const node = document.createElement(tag);
	if (className) node.className = className;
	if (text) node.textContent = text;
	return node;
}

export function textButton(label, className = "pager-button") {
	const button = element("button", className, label);
	button.type = "button";
	return button;
}
