import {
  Beer,
  Coffee,
  Cookie,
  CupSoda,
  Drumstick,
  Fish,
  IceCream,
  Martini,
  Pizza,
  Popcorn,
  Salad,
  Sandwich,
  Soup,
  Star,
  Tag,
  UtensilsCrossed,
  Wine,
  type LucideIcon,
} from "lucide-react";

/** Category colours: the reference palette's eight slots in fixed order. A ninth
 * category gets the neutral "other" colour; colours are never cycled. */
export function categoryColor(index: number): string {
  return index >= 0 && index < 8 ? `var(--cat-${index + 1})` : "var(--cat-other)";
}

const ICONS: [RegExp, LucideIcon][] = [
  [/beer|lager|cider/, Beer],
  [/wine|champagne/, Wine],
  [/spirit|whisk|vodka|gin|rum|brandy|tequila|cocktail|shot/, Martini],
  [/soft|soda|juice|water|energy|drink/, CupSoda],
  [/coffee|tea|hot/, Coffee],
  [/fish|sea/, Fish],
  [/grill|meat|choma|chicken|bbq|nyama/, Drumstick],
  [/pizza/, Pizza],
  [/burger|sandwich|wrap/, Sandwich],
  [/soup|stew/, Soup],
  [/salad|veg/, Salad],
  [/dessert|sweet|ice/, IceCream],
  [/snack|bite|chips/, Popcorn],
  [/bakery|cake|biscuit/, Cookie],
  [/main|food|meal|kitchen|dish/, UtensilsCrossed],
];

export function categoryIcon(name: string): LucideIcon {
  const n = name.toLowerCase();
  return ICONS.find(([re]) => re.test(n))?.[1] ?? Tag;
}

export const FavouritesIcon = Star;

export function initials(name: string): string {
  const parts = name.trim().split(/\s+/);
  return (parts[0][0] + (parts.length > 1 ? parts[parts.length - 1][0] : parts[0][1] ?? "")).toUpperCase();
}

/** "12 min", "1h 05" since a moment. */
export function since(iso: string, now = Date.now()): string {
  const minutes = Math.max(0, Math.floor((now - new Date(iso).getTime()) / 60000));
  if (minutes < 60) return `${minutes} min`;
  return `${Math.floor(minutes / 60)}h ${String(minutes % 60).padStart(2, "0")}`;
}
