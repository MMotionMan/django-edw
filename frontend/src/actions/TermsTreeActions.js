import {
    LOAD_ITEM,
    LOAD_TREE,
    RELOAD_TREE,
    TOGGLE_FILTERS,
    TOGGLE_ITEM,
    RESET_ITEM,
    RESET_BRANCH,
    SHOW_INFO,
    HIDE_INFO,
    NOTIFY_LOADING,
} from '../constants/TermsTree.js';
import reCache from '../utils/reCache';
import Singleton from '../utils/singleton';


const globalStore = new Singleton();

/*
Функция для получения дерева терминов
:param type: Тип вызванного действия
:param mart_id: Id витрины данных
:param selected: Массив выбранных терминов
*/
const getTermsTree = (type, mart_id, selected = []) => dispatch => {
  let url = Urls['edw:data-mart-term-tree'](mart_id, 'json');
  url = reCache(url);

  if (selected && selected.length > 0)
    url += '&selected=' + selected.join();

  return fetch(url, {
    method: 'get',
    headers: {
      'Accept': 'application/json',
      'Content-Type': 'application/json'
    },
  }).then(response => response.json()).then(json => {
    dispatch({
      type: type,
      json: json,
    })
  });
};


export const getTermsItem = url => dispatch => {
  fetch(reCache(url), {
    method: 'get',
    headers: {
      'Accept': 'application/json',
      'Content-Type': 'application/json'
    },
  }).then(response => response.json()).then(json => dispatch({
    type: LOAD_ITEM,
    json: json,
  }));
};


export const notifyLoading = () => dispatch => {
  dispatch({type: NOTIFY_LOADING});
};


export const loadTree = (mart_id, selected = [])  => {
  return getTermsTree(LOAD_TREE, mart_id, selected);
};


export const reloadTree = (mart_id, selected = []) => {
  return getTermsTree(RELOAD_TREE, mart_id, selected);
};


export function readTree(mart_id, selected = []) {
  const type = LOAD_TREE;
  if (globalStore.initial_trees && globalStore.initial_trees[mart_id]) {
    const json = globalStore.initial_trees[mart_id];
    return dispatch => {
      dispatch({ type, json });
    };
  } else {
    return getTermsTree(type, mart_id, selected);
  }
}

export const toggleFilters = () => dispatch => {
  dispatch({type: TOGGLE_FILTERS})
};

export function toggle(term = {}) {
  return dispatch => {
    dispatch({
      type: TOGGLE_ITEM,
      term: term
    });
  };
}


export function resetItem(term = {}) {
  return dispatch => {
    dispatch({
      type: RESET_ITEM,
      term: term
    });
  };
}


export function resetBranch(term = {}) {
  return dispatch => {
    dispatch({
      type: RESET_BRANCH,
      term: term
    });
  };
}


export function showInfo(term = {}) {
  return dispatch => {
    dispatch({
      type: SHOW_INFO,
      term: term
    });
  };
}


export function hideInfo(term = {}) {
   return dispatch => {
    dispatch({
      type: HIDE_INFO,
      term: term
    });
  };
}
