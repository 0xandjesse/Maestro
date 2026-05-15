export default {
  preset: 'ts-jest/presets/default-esm',
  extensionsToTreatAsEsm: ['.ts'],
  moduleNameMapper: {
    '^(\\.{1,2}/.*)\\.js$': '$1',
  },
  transform: {
    '^.+\\.tsx?$': [
      'ts-jest',
      {
        useESM: true,
      },
    ],
  },
  testEnvironment: 'node',
  testMatch: ['**/__tests__/**/*.test.ts', '**/*.test.ts'],
  testPathIgnorePatterns: [
    '/node_modules/',
    '/maestro-protocol/',
    '/maestro-protocol-backup-v0.2.0/',
  ],
  collectCoverageFrom: ['src/**/*.ts', '!src/**/*.d.ts'],
};
