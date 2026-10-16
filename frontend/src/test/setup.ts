import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

afterEach(() => {
  cleanup();
});

if (!document.elementFromPoint) {
  document.elementFromPoint = () => null;
}

const rect = () => new DOMRect();

Range.prototype.getBoundingClientRect = rect;
Range.prototype.getClientRects = () => document.createDocumentFragment().childNodes as unknown as DOMRectList;

const elementProto = Element.prototype as Element & {
  getClientRects?: () => DOMRectList;
  getBoundingClientRect?: () => DOMRect;
};
elementProto.getClientRects = () => document.createDocumentFragment().childNodes as unknown as DOMRectList;
if (!elementProto.getBoundingClientRect) {
  elementProto.getBoundingClientRect = rect;
}

HTMLElement.prototype.scrollIntoView = () => {};
