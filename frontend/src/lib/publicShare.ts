export function parsePublicShareLocation(pathname: string, hash: string) {
  const match = pathname.match(
    /^\/share\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\/?$/i,
  );
  if (!match) return null;
  const secret = hash.startsWith("#") ? hash.slice(1) : hash;
  if (secret && !/^[A-Za-z0-9_-]{32,128}$/.test(secret)) return null;
  return { shareId: match[1].toLowerCase(), secret };
}
