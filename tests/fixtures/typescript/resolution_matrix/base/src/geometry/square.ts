export interface Shape {
  area(): number;
  label: string;
}

export const SCALE: number = 2;

export class Square implements Shape {
  label = "square";
  size: number;

  constructor(size: number) {
    this.size = size;
  }

  area(): number {
    return this.size * this.size;
  }
}
