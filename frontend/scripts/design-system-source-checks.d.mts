export declare function standalonePlaceholderViolations(
  source: string,
  label: string,
  ownsProductUi: boolean,
): string[];

export declare function productUiSourceViolations(
  source: string,
  label: string,
  ownsProductUi: boolean,
): string[];

export declare function productControlViolations(
  source: string,
  label: string,
  ownsProductUi: boolean,
): string[];

export declare function directRadixImportViolations(source: string, label: string): string[];

export declare function textRoleBackgroundViolations(source: string, label: string): string[];
