import React, { Component } from 'react';
import { connect } from 'react-redux';
import { bindActionCreators } from 'redux';
import Actions from '../actions/index';
import { setOffset } from '../utils/locationHash';
import parseRequestParams from 'utils/parseRequestParams';


class Paginator extends Component {

  constructor() {
    super();
    this.state = {
      options_arr: [],
    };
  }

  requestOptions(){
    const { entry_points, entry_point_id } = this.props,
          request_params = entry_points && entry_points[entry_point_id].request_params || [],
          parms = parseRequestParams(request_params);
    return parms.options_arr || [];
  }

  handleNextClick(e) {
    e.preventDefault();
    e.stopPropagation();
    const meta = this.props.entities.items.meta;
    const { subj_ids, limit, offset, request_options } = meta;
    let options = Object.assign(request_options, {'offset': offset + limit});
    this.props.actions.notifyLoadingEntities();
    setOffset(this.props.entry_point_id, options.offset);
    this.props.actions.getEntities(this.props.entry_point_id, subj_ids, options, this.state.options_arr);
  }

  handlePrevClick(e) {
    e.preventDefault();
    e.stopPropagation();
    const meta = this.props.entities.items.meta;
    const { subj_ids, limit, offset, request_options } = meta;
    let options = Object.assign(request_options, {'offset': offset - limit});
    this.props.actions.notifyLoadingEntities();
    setOffset(this.props.entry_point_id, options.offset);
    this.props.actions.getEntities(this.props.entry_point_id, subj_ids, options, this.state.options_arr);
  }

  handlePageClick(e, n) {
    e.preventDefault();
    e.stopPropagation();
    const meta = this.props.entities.items.meta;
    const { subj_ids, limit, request_options } = meta;
    let options = Object.assign(request_options, {'offset': limit * (n - 1)});
    this.props.actions.notifyLoadingEntities();
    setOffset(this.props.entry_point_id, options.offset);
    this.props.actions.getEntities(this.props.entry_point_id, subj_ids, options, this.state.options_arr);
  }

  componentDidMount() {
    this.setState({
      options_arr: this.requestOptions(),
    });
  }

  render() {

    const meta = this.props.entities.items.meta;

    let range = function(start = 0, stop, step = 1) {
      let ret = [];
      let cur = (stop === undefined) ? 0 : start;
      let max = (stop === undefined) ? start : stop;
      for (let i = cur; step < 0 ? i > max : i < max; i += step)
        ret.push(i);
      return ret;
    };

    // Digg-style pagination settings
    const leadingPageRangeDisplayed = 8,
          trailingPageRangeDisplayed = 8,
          leadingPageRange = 6,
          trailingPageRange = 6,
          numPagesOutsideRange = 2,
          adjacentPages = 2;

    const { limit, offset, count } = meta;


    let inLeadingRange = false,
        inTrailingRange = false,
        pagesOutsideLeadingRange = range(0),
        pagesOutsideTrailingRange = range(0),
        currentPage = Math.floor(offset / limit) + 1,
        numPages = Math.ceil(count / limit),
        pageNumbers;

    if (!(limit && count) || numPages < 2)
      return <div/>;

    if ( numPages <= leadingPageRangeDisplayed + numPagesOutsideRange + 1 ) {
      inLeadingRange = inTrailingRange = true;
      pageNumbers = range(1, numPages + 1).filter(
        n => n > 0 && n <= numPages
      );
    } else if ( currentPage <= leadingPageRange ) {
      inLeadingRange = true;
      pageNumbers = range(1, leadingPageRangeDisplayed + 1).filter(
        n => n > 0 && n <= numPages
      );
      pagesOutsideLeadingRange = range(0, -1 * numPagesOutsideRange, -1).map(
        n => n + numPages
      );
    } else if ( currentPage > numPages - trailingPageRange ) {
      inTrailingRange = true;
      pageNumbers = range(numPages - trailingPageRangeDisplayed + 1, numPages + 1).filter(
        n => n > 0 && n <= numPages
      );
      pagesOutsideTrailingRange = range(0, numPagesOutsideRange).map(
        n => n + 1
      );
    } else {
      pageNumbers = range(currentPage - adjacentPages, currentPage + adjacentPages + 1).filter(
        n => n > 0 && n <= numPages
      );
      pagesOutsideLeadingRange = range(0, -1 * numPagesOutsideRange, -1).map(
        n => n + numPages
      );
      pagesOutsideTrailingRange = range(0, numPagesOutsideRange).map(
        n => n + 1
      );
    }

    let hasNext = currentPage < numPages,
        hasPrevious = currentPage > 1;

    let previous = '';
    if (hasPrevious) {
      previous = (
        <li key="prev" onClick={e => { ::this.handlePrevClick(e);}}>
          <a href="#"><i className="ex-icon-chevron-left"/></a>
        </li>
      );
    } else {
      previous = (
        <li key="prev" className="ex-disabled">
          <span><i className="ex-icon-chevron-left"/></span>
        </li>
      );
    }

    let self = this;

    let pages = [];
    if ( !inLeadingRange ) {
      pagesOutsideTrailingRange.forEach(function(n) {
        pages.push(
          <li key={n} onClick={e => { ::self.handlePageClick(e, n);}}>
            <a href="#">{n}</a>
          </li>
        );
      });
      pages.push(
        <li key="lead-sep"><span className="ex-separator">…</span></li>
      );
    }

    pageNumbers.forEach(function(n) {
      if (currentPage === n) {
        pages.push(
          <li key={n} className="ex-active"><span>{n}</span></li>
        );
      } else {
        pages.push(
          <li key={n} onClick={e => { ::self.handlePageClick(e, n);}}>
            <a href="#">{n}</a>
          </li>
        );
      }
    });

    if ( !inTrailingRange ) {
      pages.push(
        <li key="trail-sep"><span className="ex-separator">…</span></li>
      );
      pagesOutsideLeadingRange.reverse().forEach(function(n) {
        pages.push(
          <li key={n} onClick={e => { ::self.handlePageClick(e, n);}}>
            <a href="#">{n}</a>
          </li>
        );
      });
    }

    let next = '';
    if (hasNext) {
      next = (
        <li key="next" onClick={e => { ::this.handleNextClick(e);}}>
          <a href="#"><i className="ex-icon-chevron-right"/></a>
        </li>
      );
    } else {
      next = (
        <li key="next" className="ex-disabled">
          <span><i className="ex-icon-chevron-right"/></span>
        </li>
      );
    }

    if (this.props.hide_page_numbers)
      pages = '';

    let ret = (
      <div className="ex-catalog-pagination">
        <ul className="ex-pagination">
          {previous}
          {pages}
          {next}
        </ul>
      </div>
    );

    return ret;
  }
}

function mapState(state) {
  return {
    entities: state.entities,
  };
}

function mapDispatch(dispatch) {
  return {
    actions: bindActionCreators(Actions, dispatch),
    dispatch: dispatch,
  };
}

export default connect(mapState, mapDispatch)(Paginator);
