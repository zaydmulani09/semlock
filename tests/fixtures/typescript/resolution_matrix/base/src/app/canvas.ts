import { Square, Shape, SCALE } from "./geometry";
import type { Shape as ShapeT } from "./geometry";

export function total(squares: Square[]): number {
  return squares.reduce((acc, s) => acc + s.area(), 0) * SCALE;
}

export function describe(shape: ShapeT): string {
  return shape.label + " " + String(total([]));
}

export function firstLabel(shapes: Shape[]): string {
  return shapes[0].label;
}
