/* View registry. Individual view modules register themselves here. */
"use strict";

const Views = {};

function registerViews(obj) {
  Object.assign(Views, obj);
}
