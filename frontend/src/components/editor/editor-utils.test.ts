import assert from "node:assert/strict";
import { test } from "node:test";

import { commandMatchesQuery, findSlashCommandRange } from "./editor-utils";

test("findSlashCommandRange opens for a slash at the start of a block", () => {
  assert.deepEqual(findSlashCommandRange("/", 14), {
    from: 14,
    to: 15,
    query: "",
  });
});

test("findSlashCommandRange includes the query in the replacement range", () => {
  assert.deepEqual(findSlashCommandRange("/заголовок 2", 7), {
    from: 7,
    to: 19,
    query: "заголовок 2",
  });
});

test("findSlashCommandRange ignores prose and URLs", () => {
  assert.equal(findSlashCommandRange("текст /", 1), null);
  assert.equal(findSlashCommandRange("https://noki.app", 1), null);
});

test("commandMatchesQuery searches Russian labels and aliases", () => {
  const command = {
    label: "Маркированный список",
    keywords: ["список", "bullet list", "ul"],
  };

  assert.equal(commandMatchesQuery(command, "маркир"), true);
  assert.equal(commandMatchesQuery(command, "BULLET"), true);
  assert.equal(commandMatchesQuery(command, "цитата"), false);
});
