import { createContext, type PropsWithChildren } from "react";
export const ThemeContext = createContext("dark");
export function ThemeProvider({ children }: PropsWithChildren<{ defaultTheme?: string }>) { return <ThemeContext.Provider value="dark">{children}</ThemeContext.Provider>; }
