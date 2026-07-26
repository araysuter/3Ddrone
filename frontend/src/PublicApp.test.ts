import { describe, expect, it } from "vitest";
import {
  artifactResourcePath,
  parsePublicShareLocation,
  publicMapResourceBase,
  publicProjectMapPath,
  publicProjectMapResourceBase,
} from "./lib/publicShare";

const SHARE_ID = "7ac8f41c-9f08-4f19-9cf6-731764941a03";
const ITEM_ID = "ab26d006-c431-4f95-9353-8c1551cb710c";

describe("parsePublicShareLocation", () => {
  it("parses typed individual-map routes", () => {
    expect(
      parsePublicShareLocation(`/share/maps/${SHARE_ID}`),
    ).toEqual({
      kind: "map",
      shareId: SHARE_ID,
    });
    expect(
      parsePublicShareLocation(`/share/maps/${SHARE_ID}/`),
    ).toEqual({
      kind: "map",
      shareId: SHARE_ID,
    });
  });

  it("parses project collection and nested-map routes", () => {
    expect(
      parsePublicShareLocation(`/share/projects/${SHARE_ID}`),
    ).toEqual({
      kind: "project",
      shareId: SHARE_ID,
      itemId: undefined,
    });
    expect(
      parsePublicShareLocation(
        `/share/projects/${SHARE_ID}/maps/${ITEM_ID}/`,
      ),
    ).toEqual({
      kind: "project",
      shareId: SHARE_ID,
      itemId: ITEM_ID,
    });
  });

  it("intentionally rejects legacy and malformed routes", () => {
    expect(parsePublicShareLocation(`/share/${SHARE_ID}`)).toBeNull();
    expect(
      parsePublicShareLocation(
        `/share/projects/${SHARE_ID}/maps/${SHARE_ID}/extra`,
      ),
    ).toBeNull();
    expect(parsePublicShareLocation("/")).toBeNull();
  });
});

describe("public project navigation and resource paths", () => {
  it("constructs reloadable nested project-map URLs", () => {
    expect(publicProjectMapPath(SHARE_ID, ITEM_ID)).toBe(
      `/share/projects/${SHARE_ID}/maps/${ITEM_ID}`,
    );
  });

  it("keeps individual and project-map resource namespaces separate", () => {
    expect(publicMapResourceBase(SHARE_ID)).toBe(
      `/api/public/map-shares/${SHARE_ID}`,
    );
    expect(publicProjectMapResourceBase(SHARE_ID, ITEM_ID)).toBe(
      `/api/public/project-shares/${SHARE_ID}/maps/${ITEM_ID}`,
    );
    expect(
      artifactResourcePath(
        publicProjectMapResourceBase(SHARE_ID, ITEM_ID),
        "artifacts/odm_report/report.pdf",
      ),
    ).toBe(
      `/api/public/project-shares/${SHARE_ID}/maps/${ITEM_ID}/artifacts/artifacts/odm_report/report.pdf`,
    );
  });
});
