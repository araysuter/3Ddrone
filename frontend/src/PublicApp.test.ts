import { describe, expect, it } from "vitest";
import { parsePublicShareLocation } from "./lib/publicShare";

describe("parsePublicShareLocation", () => {
  it("accepts only a UUID share path and URL-safe secret fragment", () => {
    expect(
      parsePublicShareLocation(
        "/share/7ac8f41c-9f08-4f19-9cf6-731764941a03",
        "#abcdefghijklmnopqrstuvwxyzABCDEFG_123456",
      ),
    ).toEqual({
      shareId: "7ac8f41c-9f08-4f19-9cf6-731764941a03",
      secret: "abcdefghijklmnopqrstuvwxyzABCDEFG_123456",
    });
    expect(parsePublicShareLocation("/", "")).toBeNull();
    expect(
      parsePublicShareLocation(
        "/share/7ac8f41c-9f08-4f19-9cf6-731764941a03",
        "#not allowed!",
      ),
    ).toBeNull();
  });

  it("allows a valid path without a fragment for an existing scoped cookie", () => {
    expect(
      parsePublicShareLocation(
        "/share/7ac8f41c-9f08-4f19-9cf6-731764941a03/",
        "",
      ),
    ).toEqual({
      shareId: "7ac8f41c-9f08-4f19-9cf6-731764941a03",
      secret: "",
    });
  });
});
