export function parsePublicShareLocation(pathname: string) {
  const match = pathname.match(
    /^\/share\/([0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12})\/?$/i,
  );
  if (!match) return null;
  return { shareId: match[1].toLowerCase() };
}
