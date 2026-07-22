import nextJest from "next/jest.js";

const createJestConfig = nextJest({ dir: "./" });

const config = {
  clearMocks: true,
  coverageProvider: "v8",
  moduleNameMapper: {
    "^@/(.*)$": "<rootDir>/src/$1",
  },
  modulePathIgnorePatterns: ["<rootDir>/.next/"],
  setupFilesAfterEnv: ["<rootDir>/src/test/setup.ts"],
  testEnvironment: "jsdom",
};

export default createJestConfig(config);
