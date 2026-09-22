/**
 * routingPrototype.ts
 *
 * Typed adapter holding all hardcoded routing prototype state that the
 * RoutingPopover currently displayed inline.
 *
 * Routing Studio v2 will replace this module's consumers with live
 * /v1/routing/* API calls.  Until then this provides a single typed seam
 * so that:
 *  - Components never contain product routing data.
 *  - Tests can assert against typed constants rather than UI text.
 *  - The future live swap is a single import path change.
 */

export interface RoutingPrototypeRoute {
  /** Specialist name shown in the route table */
  specialist: string;
  /** Model identifier shown in the route table */
  model: string;
  /** Reasoning level label shown in the route table */
  reasoning: string;
}

export interface RoutingPrototypeSettings {
  /** Active profile name */
  profileName: string;
  /** Profile scope descriptor */
  scope: string;
  /** Privacy setting label */
  privacy: string;
  /** Fallback strategy label */
  fallback: string;
}

export interface RoutingPrototypeState {
  settings: RoutingPrototypeSettings;
  routes: RoutingPrototypeRoute[];
}

/** The single source of truth for RoutingPopover prototype data. */
export const routingPrototypeState: RoutingPrototypeState = {
  settings: {
    profileName: 'Balanced',
    scope: 'Session',
    privacy: 'Internal',
    fallback: 'Ask before cloud',
  },
  routes: [
    { specialist: 'Root',     model: 'Auto',    reasoning: 'Adaptive'  },
    { specialist: 'Research', model: 'Model R', reasoning: 'Med→High'  },
    { specialist: 'Coding',   model: 'Model C', reasoning: 'High'      },
    { specialist: 'Writing',  model: 'Model W', reasoning: 'Medium'    },
  ],
};
