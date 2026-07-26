import { describe, expect, it } from "vitest";
import { parsePublicShareLocation } from "./lib/publicShare";

describe("parsePublicShareLocation", () => {
  it("accepts a UUID public-share path", () => {
    expect(
      parsePublicShareLocation("/share/7ac8f41c-9f08-4f19-9cf6-731764941a03"),
    ).toEqual({
      shareId: "7ac8f41c-9f08-4f19-9cf6-731764941a03",
    });
    expect(parsePublicShareLocation("/")).toBeNull();
  });

  it("allows a trailing slash", () => {
    expect(
      parsePublicShareLocation("/share/7ac8f41c-9f08-4f19-9cf6-731764941a03/"),
    ).toEqual({
      shareId: "7ac8f41c-9f08-4f19-9cf6-731764941a03",
    });
  });
});
