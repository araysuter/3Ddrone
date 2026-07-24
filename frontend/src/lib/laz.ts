export const ODM_LAZ_OPTIONS = {
  las: {
    colorDepth: "auto",
    fp64: true,
    // LAZRsLoader.parse() is a direct parser call and does not merge the
    // LASWorkerLoader defaults. An omitted skip becomes NaN inside its chunk
    // reader, producing an empty batch and "Point index out of range".
    skip: 1,
  },
} as const;
