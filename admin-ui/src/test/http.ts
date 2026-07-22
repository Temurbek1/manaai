export function requestUrl(input: RequestInfo | URL): string {
  if (typeof input === "string") return input;
  if (input instanceof URL) return input.toString();
  return input.url;
}

export function requestBodyText(body: BodyInit | null | undefined): string {
  if (typeof body !== "string") {
    throw new Error("Expected a JSON string request body");
  }
  return body;
}
