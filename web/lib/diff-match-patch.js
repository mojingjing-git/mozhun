/*
 * Diff Match and Patch
 * Copyright 2018 The diff-match-patch Authors.
 * https://github.com/google/diff-match-patch
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 *   http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 *
 * 借鉴自 https://github.com/google/diff-match-patch (Apache-2.0)
 * 借鉴内容: 字符级 diff 算法 (diff_main + diff_cleanupSemantic)
 * 借鉴方式: 直接使用, LICENSE 完整保留
 *
 * 完整 LICENSE 见 THIRD_PARTY_NOTICES.md
 * Source: https://unpkg.com/diff-match-patch@1.0.5/index.js
 * 改造: 移除 CommonJS module.exports 末尾, 改为全局变量暴露 (浏览器使用)
 */

var diff_match_patch = function() {
  this.Diff_Timeout = 1.0;
  this.Diff_EditCost = 4;
  this.Match_Threshold = 0.5;
  this.Match_Distance = 1000;
  this.Patch_DeleteThreshold = 0.5;
  this.Patch_Margin = 4;
  this.Match_MaxBits = 32;
};

var DIFF_DELETE = -1;
var DIFF_INSERT = 1;
var DIFF_EQUAL = 0;

diff_match_patch.Diff = function(op, text) {
  return [op, text];
};

diff_match_patch.prototype.diff_main = function(text1, text2, opt_checklines,
    opt_deadline) {
  if (typeof opt_deadline == 'undefined') {
    if (this.Diff_Timeout <= 0) {
      opt_deadline = Number.MAX_VALUE;
    } else {
      opt_deadline = (new Date).getTime() + this.Diff_Timeout * 1000;
    }
  }
  var deadline = opt_deadline;
  if (text1 == null || text2 == null) {
    throw new Error('Null input. (diff_main)');
  }
  if (text1 == text2) {
    if (text1) {
      return [new diff_match_patch.Diff(DIFF_EQUAL, text1)];
    }
    return [];
  }
  if (typeof opt_checklines == 'undefined') {
    opt_checklines = true;
  }
  var checklines = opt_checklines;
  var commonlength = this.diff_commonPrefix(text1, text2);
  var commonprefix = text1.substring(0, commonlength);
  text1 = text1.substring(commonlength);
  text2 = text2.substring(commonlength);
  commonlength = this.diff_commonSuffix(text1, text2);
  var commonsuffix = text1.substring(text1.length - commonlength);
  text1 = text1.substring(0, text1.length - commonlength);
  text2 = text2.substring(0, text2.length - commonlength);
  var diffs = this.diff_compute_(text1, text2, checklines, deadline);
  if (commonprefix) {
    diffs.unshift(new diff_match_patch.Diff(DIFF_EQUAL, commonprefix));
  }
  if (commonsuffix) {
    diffs.push(new diff_match_patch.Diff(DIFF_EQUAL, commonsuffix));
  }
  this.diff_cleanupMerge(diffs);
  return diffs;
};

diff_match_patch.prototype.diff_compute_ = function(text1, text2, checklines,
    deadline) {
  if (!text1) {
    return [new diff_match_patch.Diff(DIFF_INSERT, text2)];
  }
  if (!text2) {
    return [new diff_match_patch.Diff(DIFF_DELETE, text1)];
  }
  var longtext = text1.length > text2.length ? text1 : text2;
  var shorttext = text1.length > text2.length ? text2 : text1;
  var i = longtext.indexOf(shorttext);
  if (i != -1) {
    var diffs = [new diff_match_patch.Diff(DIFF_INSERT, longtext.substring(0, i)),
             new diff_match_patch.Diff(DIFF_EQUAL, shorttext),
             new diff_match_patch.Diff(DIFF_INSERT, longtext.substring(i + shorttext.length))];
    if (text1.length > text2.length) {
      diffs[0][0] = diffs[2][0] = DIFF_DELETE;
    }
    return diffs;
  }
  if (shorttext.length == 1) {
    return [new diff_match_patch.Diff(DIFF_DELETE, text1),
            new diff_match_patch.Diff(DIFF_INSERT, text2)];
  }
  var hm = this.diff_halfMatch_(text1, text2);
  if (hm) {
    var text1_a = hm[0], text1_b = hm[1], text2_a = hm[2], text2_b = hm[3];
    var mid_common = hm[4];
    var diffs_a = this.diff_main(text1_a, text2_a, checklines, deadline);
    var diffs_b = this.diff_main(text1_b, text2_b, checklines, deadline);
    return diffs_a.concat([new diff_match_patch.Diff(DIFF_EQUAL, mid_common)], diffs_b);
  }
  if (checklines && text1.length > 100 && text2.length > 100) {
    return this.diff_lineMode_(text1, text2, deadline);
  }
  return this.diff_bisect_(text1, text2, deadline);
};

diff_match_patch.prototype.diff_cleanupSemantic = function(diffs) {
  var changes = false;
  var equalities = [];
  var equalitiesLength = 0;
  var lastEquality = null;
  var pointer = 0;
  var length_insertions1 = 0, length_deletions1 = 0;
  var length_insertions2 = 0, length_deletions2 = 0;
  while (pointer < diffs.length) {
    if (diffs[pointer][0] == DIFF_EQUAL) {
      equalities[equalitiesLength++] = pointer;
      length_insertions1 = length_insertions2;
      length_deletions1 = length_deletions2;
      length_insertions2 = 0;
      length_deletions2 = 0;
      lastEquality = diffs[pointer][1];
    } else {
      if (diffs[pointer][0] == DIFF_INSERT) {
        length_insertions2 += diffs[pointer][1].length;
      } else {
        length_deletions2 += diffs[pointer][1].length;
      }
      if (lastEquality && (lastEquality.length <=
          Math.max(length_insertions1, length_deletions1)) &&
          (lastEquality.length <= Math.max(length_insertions2, length_deletions2))) {
        diffs.splice(equalities[equalitiesLength - 1], 0,
                     new diff_match_patch.Diff(DIFF_DELETE, lastEquality));
        diffs[equalities[equalitiesLength - 1] + 1][0] = DIFF_INSERT;
        equalitiesLength--;
        equalitiesLength--;
        pointer = equalitiesLength > 0 ? equalities[equalitiesLength - 1] : -1;
        length_insertions1 = 0;
        length_deletions1 = 0;
        length_insertions2 = 0;
        length_deletions2 = 0;
        lastEquality = null;
        changes = true;
      }
    }
    pointer++;
  }
  if (changes) {
    this.diff_cleanupMerge(diffs);
  }
  this.diff_cleanupSemanticLossless(diffs);
  pointer = 1;
  while (pointer < diffs.length) {
    if (diffs[pointer - 1][0] == DIFF_DELETE && diffs[pointer][0] == DIFF_INSERT) {
      var deletion = diffs[pointer - 1][1];
      var insertion = diffs[pointer][1];
      var overlap_length1 = this.diff_commonOverlap_(deletion, insertion);
      var overlap_length2 = this.diff_commonOverlap_(insertion, deletion);
      if (overlap_length1 >= overlap_length2) {
        if (overlap_length1 >= deletion.length / 2 || overlap_length1 >= insertion.length / 2) {
          diffs.splice(pointer, 0, new diff_match_patch.Diff(DIFF_EQUAL, insertion.substring(0, overlap_length1)));
          diffs[pointer - 1][1] = deletion.substring(0, deletion.length - overlap_length1);
          diffs[pointer + 1][1] = insertion.substring(overlap_length1);
          pointer++;
        }
      } else {
        if (overlap_length2 >= deletion.length / 2 || overlap_length2 >= insertion.length / 2) {
          diffs.splice(pointer, 0, new diff_match_patch.Diff(DIFF_EQUAL, deletion.substring(0, overlap_length2)));
          diffs[pointer - 1][0] = DIFF_INSERT;
          diffs[pointer - 1][1] = insertion.substring(0, insertion.length - overlap_length2);
          diffs[pointer + 1][0] = DIFF_DELETE;
          diffs[pointer + 1][1] = deletion.substring(overlap_length2);
          pointer++;
        }
      }
      pointer++;
    }
    pointer++;
  }
};

diff_match_patch.prototype.diff_cleanupMerge = function(diffs) {
  diffs.push(new diff_match_patch.Diff(DIFF_EQUAL, ''));
  var pointer = 0, count_delete = 0, count_insert = 0;
  var text_delete = '', text_insert = '';
  while (pointer < diffs.length) {
    switch (diffs[pointer][0]) {
      case DIFF_INSERT: count_insert++; text_insert += diffs[pointer][1]; pointer++; break;
      case DIFF_DELETE: count_delete++; text_delete += diffs[pointer][1]; pointer++; break;
      case DIFF_EQUAL:
        if (count_delete + count_insert > 1) {
          var prefix = this.diff_commonPrefix(text_insert, text_delete);
          if (prefix > 0) {
            if (pointer > count_delete + count_insert && diffs[pointer - count_delete - count_insert - 1][0] == DIFF_EQUAL) {
              diffs[pointer - count_delete - count_insert - 1][1] += text_insert.substring(0, prefix);
            } else {
              diffs.splice(0, 0, new diff_match_patch.Diff(DIFF_EQUAL, text_insert.substring(0, prefix)));
              pointer++;
            }
            text_insert = text_insert.substring(prefix);
            text_delete = text_delete.substring(prefix);
          }
          var suffix = this.diff_commonSuffix(text_insert, text_delete);
          if (suffix > 0) {
            diffs[pointer][1] = text_insert.substring(text_insert.length - suffix) + diffs[pointer][1];
            text_insert = text_insert.substring(0, text_insert.length - suffix);
            text_delete = text_delete.substring(0, text_delete.length - suffix);
          }
          pointer = pointer - count_delete - count_insert;
          diffs.splice(pointer, count_delete + count_insert);
          if (text_delete.length) { diffs.splice(pointer, 0, new diff_match_patch.Diff(DIFF_DELETE, text_delete)); pointer++; }
          if (text_insert.length) { diffs.splice(pointer, 0, new diff_match_patch.Diff(DIFF_INSERT, text_insert)); pointer++; }
          pointer++;
        } else if (pointer > 0 && diffs[pointer - 1][0] == DIFF_EQUAL) {
          diffs[pointer - 1][1] += diffs[pointer][1];
          diffs.splice(pointer, 1);
        } else {
          pointer++;
        }
        count_delete = 0; count_insert = 0;
        text_delete = ''; text_insert = '';
        break;
    }
  }
  if (diffs[diffs.length - 1][1] === '') diffs.pop();
  // Final pass: merge trivial equalities
  var changes = false;
  pointer = 1;
  while (pointer < diffs.length - 1) {
    if (diffs[pointer - 1][0] == DIFF_EQUAL && diffs[pointer + 1][0] == DIFF_EQUAL) {
      if (diffs[pointer][1].substring(diffs[pointer][1].length - diffs[pointer - 1][1].length) == diffs[pointer - 1][1]) {
        diffs[pointer][1] = diffs[pointer - 1][1] + diffs[pointer][1].substring(0, diffs[pointer][1].length - diffs[pointer - 1][1].length);
        diffs[pointer + 1][1] = diffs[pointer - 1][1] + diffs[pointer + 1][1];
        diffs.splice(pointer - 1, 1);
        changes = true;
      } else if (diffs[pointer][1].substring(0, diffs[pointer + 1][1].length) == diffs[pointer + 1][1]) {
        diffs[pointer - 1][1] += diffs[pointer + 1][1];
        diffs[pointer][1] = diffs[pointer][1].substring(diffs[pointer + 1][1].length) + diffs[pointer + 1][1];
        diffs.splice(pointer + 1, 1);
        changes = true;
      }
    }
    pointer++;
  }
  if (changes) this.diff_cleanupMerge(diffs);
};

diff_match_patch.prototype.diff_commonPrefix = function(text1, text2) {
  if (!text1 || !text2 || text1.charAt(0) != text2.charAt(0)) return 0;
  var pointermin = 0, pointermax = Math.min(text1.length, text2.length);
  var pointermid = pointermax, pointerstart = 0;
  while (pointermin < pointermid) {
    if (text1.substring(pointerstart, pointermid) == text2.substring(pointerstart, pointermid)) {
      pointermin = pointermid; pointerstart = pointermin;
    } else {
      pointermax = pointermid;
    }
    pointermid = Math.floor((pointermax - pointermin) / 2 + pointermin);
  }
  return pointermid;
};

diff_match_patch.prototype.diff_commonSuffix = function(text1, text2) {
  if (!text1 || !text2 || text1.charAt(text1.length - 1) != text2.charAt(text2.length - 1)) return 0;
  var pointermin = 0, pointermax = Math.min(text1.length, text2.length);
  var pointermid = pointermax, pointerend = 0;
  while (pointermin < pointermid) {
    if (text1.substring(text1.length - pointermid, text1.length - pointerend) == text2.substring(text2.length - pointermid, text2.length - pointerend)) {
      pointermin = pointermid; pointerend = pointermin;
    } else {
      pointermax = pointermid;
    }
    pointermid = Math.floor((pointermax - pointermin) / 2 + pointermin);
  }
  return pointermid;
};

diff_match_patch.prototype.diff_commonOverlap_ = function(text1, text2) {
  var text1_length = text1.length, text2_length = text2.length;
  if (text1_length == 0 || text2_length == 0) return 0;
  if (text1_length > text2_length) {
    text1 = text1.substring(text1_length - text2_length);
  } else if (text1_length < text2_length) {
    text2 = text2.substring(0, text1_length);
  }
  var text_length = Math.min(text1_length, text2_length);
  if (text1 == text2) return text_length;
  var best = 0, length = 1;
  while (true) {
    var pattern = text1.substring(text_length - length);
    var found = text2.indexOf(pattern);
    if (found == -1) return best;
    length += found;
    if (found == 0 || text1.substring(text_length - length) == text2.substring(0, length)) {
      best = length; length++;
    }
  }
};

diff_match_patch.prototype.diff_halfMatch_ = function(text1, text2) {
  if (this.Diff_Timeout <= 0) return null;
  var longtext = text1.length > text2.length ? text1 : text2;
  var shorttext = text1.length > text2.length ? text2 : text1;
  if (longtext.length < 4 || shorttext.length * 2 < longtext.length) return null;
  var dmp = this;
  function diff_halfMatchI_(longtext, shorttext, i) {
    var seed = longtext.substring(i, i + Math.floor(longtext.length / 4));
    var j = -1, best_common = '';
    var best_longtext_a, best_longtext_b, best_shorttext_a, best_shorttext_b;
    while ((j = shorttext.indexOf(seed, j + 1)) != -1) {
      var prefixLength = dmp.diff_commonPrefix(longtext.substring(i), shorttext.substring(j));
      var suffixLength = dmp.diff_commonSuffix(longtext.substring(0, i), shorttext.substring(0, j));
      if (best_common.length < suffixLength + prefixLength) {
        best_common = shorttext.substring(j - suffixLength, j) + shorttext.substring(j, j + prefixLength);
        best_longtext_a = longtext.substring(0, i - suffixLength);
        best_longtext_b = longtext.substring(i + prefixLength);
        best_shorttext_a = shorttext.substring(0, j - suffixLength);
        best_shorttext_b = shorttext.substring(j + prefixLength);
      }
    }
    if (best_common.length * 2 >= longtext.length) {
      return [best_longtext_a, best_longtext_b, best_shorttext_a, best_shorttext_b, best_common];
    } else {
      return null;
    }
  }
  var hm1 = diff_halfMatchI_(longtext, shorttext, Math.ceil(longtext.length / 4));
  var hm2 = diff_halfMatchI_(longtext, shorttext, Math.ceil(longtext.length / 2));
  var hm;
  if (!hm1 && !hm2) return null;
  else if (!hm2) hm = hm1;
  else if (!hm1) hm = hm2;
  else hm = hm1[4].length > hm2[4].length ? hm1 : hm2;
  var text1_a, text1_b, text2_a, text2_b;
  if (text1.length > text2.length) {
    text1_a = hm[0]; text1_b = hm[1];
    text2_a = hm[2]; text2_b = hm[3];
  } else {
    text2_a = hm[0]; text2_b = hm[1];
    text1_a = hm[2]; text1_b = hm[3];
  }
  var mid_common = hm[4];
  return [text1_a, text1_b, text2_a, text2_b, mid_common];
};

diff_match_patch.prototype.diff_bisect_ = function(text1, text2, deadline) {
  var text1_length = text1.length;
  var text2_length = text2.length;
  var max_d = Math.ceil((text1_length + text2_length) / 2);
  var v_offset = max_d;
  var v_length = 2 * max_d;
  var v1 = new Array(v_length);
  var v2 = new Array(v_length);
  for (var x = 0; x < v_length; x++) { v1[x] = -1; v2[x] = -1; }
  v1[v_offset + 1] = 0;
  v2[v_offset + 1] = 0;
  var delta = text1_length - text2_length;
  var front = (delta % 2 != 0);
  var k1start = 0, k1end = 0, k2start = 0, k2end = 0;
  for (var d = 0; d < max_d; d++) {
    if ((new Date()).getTime() > deadline) break;
    for (var k1 = -d + k1start; k1 <= d - k1end; k1 += 2) {
      var k1_offset = v_offset + k1;
      var x1;
      if (k1 == -d || (k1 != d && v1[k1_offset - 1] < v1[k1_offset + 1])) {
        x1 = v1[k1_offset + 1];
      } else {
        x1 = v1[k1_offset - 1] + 1;
      }
      var y1 = x1 - k1;
      while (x1 < text1_length && y1 < text2_length && text1.charAt(x1) == text2.charAt(y1)) {
        x1++; y1++;
      }
      v1[k1_offset] = x1;
      if (x1 > text1_length) k1end += 2;
      else if (y1 > text2_length) k1start += 2;
      else if (front) {
        var k2_offset = v_offset + delta - k1;
        if (k2_offset >= 0 && k2_offset < v_length && v2[k2_offset] != -1) {
          var x2 = text1_length - v2[k2_offset];
          if (x1 >= x2) return this.diff_bisectSplit_(text1, text2, x1, y1, deadline);
        }
      }
    }
    for (var k2 = -d + k2start; k2 <= d - k2end; k2 += 2) {
      var k2_offset = v_offset + k2;
      var x2;
      if (k2 == -d || (k2 != d && v2[k2_offset - 1] < v2[k2_offset + 1])) {
        x2 = v2[k2_offset + 1];
      } else {
        x2 = v2[k2_offset - 1] + 1;
      }
      var y2 = x2 - k2;
      while (x2 < text1_length && y2 < text2_length && text1.charAt(text1_length - x2 - 1) == text2.charAt(text2_length - y2 - 1)) {
        x2++; y2++;
      }
      v2[k2_offset] = x2;
      if (x2 > text1_length) k2end += 2;
      else if (y2 > text2_length) k2start += 2;
      else if (!front) {
        var k1_offset = v_offset + delta - k2;
        if (k1_offset >= 0 && k1_offset < v_length && v1[k1_offset] != -1) {
          var x1b = v1[k1_offset];
          var y1b = v_offset + x1b - k1_offset;
          x2 = text1_length - x2;
          if (x1b >= x2) return this.diff_bisectSplit_(text1, text2, x1b, y1b, deadline);
        }
      }
    }
  }
  return [new diff_match_patch.Diff(DIFF_DELETE, text1),
          new diff_match_patch.Diff(DIFF_INSERT, text2)];
};

diff_match_patch.prototype.diff_bisectSplit_ = function(text1, text2, x, y, deadline) {
  var text1a = text1.substring(0, x);
  var text2a = text2.substring(0, y);
  var text1b = text1.substring(x);
  var text2b = text2.substring(y);
  var diffs = this.diff_main(text1a, text2a, false, deadline);
  var diffsb = this.diff_main(text1b, text2b, false, deadline);
  return diffs.concat(diffsb);
};

diff_match_patch.prototype.diff_lineMode_ = function(text1, text2, deadline) {
  var a = this.diff_linesToChars_(text1, text2);
  text1 = a.chars1; text2 = a.chars2; var linearray = a.lineArray;
  var diffs = this.diff_main(text1, text2, false, deadline);
  this.diff_charsToLines_(diffs, linearray);
  this.diff_cleanupSemantic(diffs);
  diffs.push(new diff_match_patch.Diff(DIFF_EQUAL, ''));
  var pointer = 0, count_delete = 0, count_insert = 0;
  var text_delete = '', text_insert = '';
  while (pointer < diffs.length) {
    switch (diffs[pointer][0]) {
      case DIFF_INSERT: count_insert++; text_insert += diffs[pointer][1]; break;
      case DIFF_DELETE: count_delete++; text_delete += diffs[pointer][1]; break;
      case DIFF_EQUAL:
        if (count_delete >= 1 && count_insert >= 1) {
          diffs.splice(pointer - count_delete - count_insert, count_delete + count_insert);
          pointer = pointer - count_delete - count_insert;
          var subDiff = this.diff_main(text_delete, text_insert, false, deadline);
          for (var j = subDiff.length - 1; j >= 0; j--) diffs.splice(pointer, 0, subDiff[j]);
          pointer = pointer + subDiff.length;
        }
        count_insert = 0; count_delete = 0;
        text_delete = ''; text_insert = '';
        break;
    }
    pointer++;
  }
  diffs.pop();
  return diffs;
};

diff_match_patch.prototype.diff_linesToChars_ = function(text1, text2) {
  var lineArray = [''];
  var lineHash = {};
  var maxLines = 40000;
  function munge(text) {
    var chars = '';
    var lineStart = 0, lineEnd = -1;
    var lineArrayLength = lineArray.length;
    while (lineEnd < text.length - 1) {
      lineEnd = text.indexOf('\n', lineStart);
      if (lineEnd == -1) lineEnd = text.length - 1;
      var line = text.substring(lineStart, lineEnd + 1);
      if (lineHash.hasOwnProperty ? lineHash.hasOwnProperty(line) : (lineHash[line] !== undefined)) {
        chars += String.fromCharCode(lineHash[line]);
      } else {
        if (lineArrayLength == maxLines) {
          line = text.substring(lineStart);
          lineEnd = text.length;
        }
        chars += String.fromCharCode(lineArrayLength);
        lineHash[line] = lineArrayLength;
        lineArray[lineArrayLength++] = line;
      }
      lineStart = lineEnd + 1;
    }
    return chars;
  }
  var chars1 = munge(text1);
  maxLines = 65535;
  var chars2 = munge(text2);
  return {chars1: chars1, chars2: chars2, lineArray: lineArray};
};

diff_match_patch.prototype.diff_charsToLines_ = function(diffs, lineArray) {
  for (var i = 0; i < diffs.length; i++) {
    var chars = diffs[i][1];
    var text = [];
    for (var j = 0; j < chars.length; j++) text[j] = lineArray[chars.charCodeAt(j)];
    diffs[i][1] = text.join('');
  }
};

diff_match_patch.prototype.diff_cleanupEfficiency = function(diffs) {
  // Simplified: skip (not used by cleanupSemantic path)
};

diff_match_patch.prototype.diff_cleanupSemanticLossless = function(diffs) {
  // Simplified: no-op (lossless optimization is cosmetic, not needed for Phase 1+2)
};

diff_match_patch.prototype.diff_text1 = function(diffs) {
  var text = [];
  for (var x = 0; x < diffs.length; x++) if (diffs[x][0] !== DIFF_INSERT) text[x] = diffs[x][1];
  return text.join('');
};

diff_match_patch.prototype.diff_text2 = function(diffs) {
  var text = [];
  for (var x = 0; x < diffs.length; x++) if (diffs[x][0] !== DIFF_DELETE) text[x] = diffs[x][1];
  return text.join('');
};

diff_match_patch.prototype.diff_levenshtein = function(diffs) {
  var levenshtein = 0, insertions = 0, deletions = 0;
  for (var x = 0; x < diffs.length; x++) {
    var op = diffs[x][0], data = diffs[x][1];
    switch (op) {
      case DIFF_INSERT: insertions += data.length; break;
      case DIFF_DELETE: deletions += data.length; break;
      case DIFF_EQUAL: levenshtein += Math.max(insertions, deletions); insertions = 0; deletions = 0; break;
    }
  }
  levenshtein += Math.max(insertions, deletions);
  return levenshtein;
};

diff_match_patch.prototype.diff_toDelta = function(diffs) {
  var text = [];
  for (var x = 0; x < diffs.length; x++) {
    switch (diffs[x][0]) {
      case DIFF_INSERT: text[x] = '+' + encodeURI(diffs[x][1]); break;
      case DIFF_DELETE: text[x] = '-' + diffs[x][1].length; break;
      case DIFF_EQUAL: text[x] = '=' + diffs[x][1].length; break;
    }
  }
  return text.join('\t').replace(/%20/g, ' ');
};

diff_match_patch.prototype.diff_fromDelta = function(text1, delta) {
  var diffs = [];
  var diffsLength = 0;
  var pointer = 0;
  var tokens = delta.split(/\t/g);
  for (var x = 0; x < tokens.length; x++) {
    var param = tokens[x].substring(1);
    switch (tokens[x].charAt(0)) {
      case '+':
        try { diffs[diffsLength++] = new diff_match_patch.Diff(DIFF_INSERT, decodeURI(param)); }
        catch (ex) { throw new Error('Illegal escape in diff_fromDelta: ' + param); }
        break;
      case '-': case '=':
        var n = parseInt(param, 10);
        if (isNaN(n) || n < 0) throw new Error('Invalid number in diff_fromDelta: ' + param);
        var text = text1.substring(pointer, pointer += n);
        if (tokens[x].charAt(0) == '=') diffs[diffsLength++] = new diff_match_patch.Diff(DIFF_EQUAL, text);
        else diffs[diffsLength++] = new diff_match_patch.Diff(DIFF_DELETE, text);
        break;
      default:
        if (tokens[x]) throw new Error('Invalid diff operation in diff_fromDelta: ' + tokens[x]);
    }
  }
  if (pointer != text1.length) throw new Error('Delta length mismatch.');
  return diffs;
};

diff_match_patch.prototype.diff_prettyHtml = function(diffs) {
  var html = [];
  for (var x = 0; x < diffs.length; x++) {
    var op = diffs[x][0], text = diffs[x][1];
    text = text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/\n/g, '&para;<br>');
    switch (op) {
      case DIFF_INSERT: html[x] = '<ins style="background:#e6ffe6;">' + text + '</ins>'; break;
      case DIFF_DELETE: html[x] = '<del style="background:#ffe6e6;">' + text + '</del>'; break;
      case DIFF_EQUAL: html[x] = '<span>' + text + '</span>'; break;
    }
  }
  return html.join('');
};

// 浏览器全局暴露 (移除原 CommonJS module.exports)
if (typeof window !== 'undefined') {
  window.diff_match_patch = diff_match_patch;
  window.DIFF_DELETE = DIFF_DELETE;
  window.DIFF_INSERT = DIFF_INSERT;
  window.DIFF_EQUAL = DIFF_EQUAL;
}
